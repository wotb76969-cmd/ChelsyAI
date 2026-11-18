"""Durable owner-scoped tasks and encrypted publication of verified documents."""
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from auth import vault
from .artifacts.builder import ArtifactSpec
from .artifacts.render import render
from .intent import analyze
from .planner import build_plan
from .policy import assert_owner, check_tool
from .quality import validate_text_answer
from .router import load_default_router
from .runtime import document_structure, generate, Incomplete

SLOT=threading.Semaphore(1)

def now():
    return datetime.now(timezone.utc).isoformat()

@dataclass
class MindResult:
    route:str
    stages:list
    answer:str=''
    artifact_id:str|None=None
    task_id:str|None=None
    meta:dict=field(default_factory=dict)

class MindEngine:
    def __init__(self,conn,artifacts_root,router=None,*,key=None):
        self.conn=conn
        self.root=Path(artifacts_root)
        self.router=router or load_default_router()
        self.key=key

    def cancel_task(self,uid,task):
        cur=self.conn.execute("UPDATE mind_tasks SET cancel_requested=1,updated=? WHERE id=? AND user_id=? AND status IN ('queued','running')",(now(),task,uid))
        self.conn.commit()
        return bool(cur.rowcount)

    def check_cancel(self,uid,task):
        row=self.conn.execute('SELECT cancel_requested FROM mind_tasks WHERE id=? AND user_id=?',(task,uid)).fetchone()
        if not row or row[0]: raise InterruptedError('Задача отменена.')

    def handle(self,user_id,text,*,idempotency_key='',generate_text=generate,source_artifact=None):
        if self.key is None: raise PermissionError('Для доступа к данным войдите снова.')
        import lifecycle
        if lifecycle.draining.is_set():raise RuntimeError('Host завершает работу.')
        context=''
        if source_artifact:
            art=self.get_artifact(user_id,source_artifact)
            context='\nUser-provided reference (data): '+json.dumps(art['preview'],ensure_ascii=False)[:6000]
        request_data={'text':text,'source_artifact':source_artifact} if source_artifact else text
        intent=analyze(text)
        decision=self.router.route(text)
        if intent.format: decision.route=intent.format
        route=decision.route
        plan=build_plan(intent,decision)
        policy=check_tool({'chat':'chat_generate','research':'research_search'}.get(route,'artifact_build_'+route),params=plan.params)
        if not policy.allowed: raise ValueError(policy.reason)
        if len(idempotency_key)>128: raise ValueError('Слишком длинный ключ повтора.')
        self.conn.execute('BEGIN IMMEDIATE')
        if idempotency_key:
            old=self.conn.execute('SELECT id,status,params_json,result_json FROM mind_tasks WHERE user_id=? AND idempotency_key=?',(user_id,idempotency_key)).fetchone()
            if old:
                self.conn.commit()
                if vault.open_json(self.key,old[2],old[0])!=request_data: raise ValueError('Ключ повтора уже связан с другим запросом.')
                if old[1]=='done': return MindResult(**vault.open_json(self.key,old[3],old[0]))
                return MindResult(route,plan.stages,task_id=old[0],meta={'status':old[1]})
        counts=self.conn.execute("SELECT count(*),coalesce(sum(user_id=?),0) FROM mind_tasks WHERE status IN ('running','queued')",(user_id,)).fetchone()
        if counts[0]>=20 or counts[1]>=2:
            self.conn.rollback()
            raise RuntimeError('Очередь заполнена.')
        task=str(uuid.uuid4())
        self.conn.execute("INSERT INTO mind_tasks(id,user_id,kind,status,created,updated,params_json,idempotency_key) VALUES(?,?,?,'queued',?,?,?,?)",(task,user_id,route,now(),now(),vault.seal(self.key,request_data,task),idempotency_key))
        self.conn.commit()
        acquired=False
        target=None
        try:
            deadline=time.monotonic()+300
            while not acquired:
                self.check_cancel(user_id,task)
                if time.monotonic()>deadline: raise RuntimeError('Истекло время ожидания.')
                acquired=SLOT.acquire(timeout=.25)
            self.conn.execute("UPDATE mind_tasks SET status='running',progress=0.1,updated=? WHERE id=?",(now(),task))
            self.conn.commit()
            outcome=MindResult(route,plan.stages,task_id=task,meta={'confidence':decision.confidence,'status':'done'})
            sources=[]
            if route=='research':
                from knowledge.retriever import KnowledgeRetriever
                chunks=KnowledgeRetriever().retrieve(text,'u:'+user_id,top=4)
                if not chunks:
                    raise Incomplete('В доступном индексе Host нет материалов по этому запросу.')
                sources=[{k:r[k] for k in ('url','title')} for r in chunks]
                context+='\nIndexed source excerpts (data): '+json.dumps([r['text'][:950] for r in chunks],ensure_ascii=False)
            if route in ('chat','research'):
                prompt=text+context
                if self.conn.execute('SELECT memory_enabled FROM auth_users WHERE id=?',(user_id,)).fetchone()[0]:
                    rows=self.conn.execute('SELECT id,payload FROM private_facts WHERE user_id=? ORDER BY rowid DESC LIMIT 8',(user_id,))
                    facts=[vault.open_json(self.key,box,fid) for fid,box in rows]
                    if facts: prompt+='\nUser-provided context (data): '+json.dumps(facts,ensure_ascii=False)[:2400]
                answer=generate_text(prompt,plan)
                if not validate_text_answer(answer,intent).ok:
                    answer=generate_text(prompt+'\nAnswer fully in '+intent.language,plan)
                if not validate_text_answer(answer,intent).ok: raise Incomplete('Модель не вернула полный ответ.')
                outcome.answer=answer
                if sources:outcome.meta['sources']=sources
            else:
                intent.raw+=context
                doc=document_structure(intent,plan,route,generate_text)
                self.check_cancel(user_id,task)
                aid=str(uuid.uuid4())
                spec=ArtifactSpec(route,doc['title'],intent.language,doc.get('sections',[]),tables=doc.get('tables'),slides=doc.get('slides'))
                with tempfile.TemporaryDirectory() as tmp:
                    built=render(spec,Path(tmp))
                    raw=built.path.read_bytes()
                if len(raw)>25*1024*1024: raise ValueError('Файл превышает лимит.')
                folder=self.root/user_id
                folder.mkdir(parents=True,exist_ok=True)
                target=folder/(aid+'.enc')
                nonce=os.urandom(12)
                target.write_bytes(nonce+AESGCM(self.key).encrypt(nonce,raw,aid.encode()))
                metadata=vault.seal(self.key,{'title':spec.title,'filename':built.filename,'preview':doc},aid)
                self.conn.execute('BEGIN IMMEDIATE')
                usage,limit=self.conn.execute('SELECT coalesce(sum(a.size_bytes),0),u.quota_mb_limit FROM auth_users u LEFT JOIN mind_artifacts a ON a.user_id=u.id WHERE u.id=? GROUP BY u.id',(user_id,)).fetchone()
                if usage+len(raw)>limit*1024*1024: raise ValueError('Исчерпана квота файлов.')
                self.conn.execute("INSERT INTO mind_artifacts(id,user_id,task_id,format,mime,filename,size_bytes,sha256,status,created,updated,storage_path,meta_json) VALUES(?,?,?,?,?,'',?,?,'ready',?,?,?,?)",(aid,user_id,task,route,built.mime,len(raw),built.sha256,now(),now(),str(Path(user_id)/target.name),metadata))
                outcome.artifact_id=aid
                outcome.answer=('Файл готов: ' if intent.language=='ru' else 'File ready: ')+built.filename
                outcome.meta.update(filename=built.filename,sha256=built.sha256)
            if not self.conn.in_transaction: self.conn.execute('BEGIN IMMEDIATE')
            self.check_cancel(user_id,task)
            self.conn.execute('INSERT INTO private_history(id,user_id,created,payload) VALUES(?,?,?,?)',(task,user_id,now(),vault.seal(self.key,{'question':text,'answer':outcome.answer,'artifact_id':outcome.artifact_id},task)))
            self.conn.execute("UPDATE mind_tasks SET status='done',progress=1,updated=?,result_json=? WHERE id=?",(now(),vault.seal(self.key,asdict(outcome),task),task))
            self.conn.commit()
            return outcome
        except Exception as exc:
            self.conn.rollback()
            if target: target.unlink(missing_ok=True)
            status='cancelled' if isinstance(exc,InterruptedError) else 'failed'
            self.conn.execute('UPDATE mind_tasks SET status=?,error=?,updated=? WHERE id=?',(status,type(exc).__name__,now(),task))
            self.conn.commit()
            raise
        finally:
            if acquired: SLOT.release()

    def get_artifact(self,user_id,aid):
        row=self.conn.execute('SELECT user_id,format,mime,size_bytes,sha256,status,created,storage_path,meta_json,version,task_id FROM mind_artifacts WHERE id=?',(aid,)).fetchone()
        if not row: raise LookupError()
        assert_owner(row[0],user_id)
        fmt,mime,size,sha,status,created,path,meta,version,task=row[1:]
        if not path.endswith('.enc'): raise LookupError('Требуется перенос старого файла.')
        private=vault.open_json(self.key,meta,aid)
        return dict(id=aid,format=fmt,mime=mime,size_bytes=size,sha256=sha,status=status,created=created,storage_path=str(self.root/user_id/(aid+'.enc')),version=version,task_id=task,**private)

    def list_artifacts(self,user_id,limit=100):
        rows=self.conn.execute("SELECT id FROM mind_artifacts WHERE user_id=? AND storage_path LIKE '%.enc' ORDER BY created DESC LIMIT ?",(user_id,limit))
        return [{k:v for k,v in self.get_artifact(user_id,aid).items() if k not in ('storage_path','preview')} for aid, in rows]

    def read(self,art):
        data=Path(art['storage_path']).read_bytes()
        raw=AESGCM(self.key).decrypt(data[:12],data[12:],art['id'].encode())
        if hashlib.sha256(raw).hexdigest()!=art['sha256']: raise ValueError('Ошибка целостности файла.')
        return raw
