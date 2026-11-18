"""Same-origin cabinet and native client API. All owner identifiers come from sessions."""
from contextlib import closing
from dataclasses import asdict
from datetime import datetime, timezone
from http.cookies import SimpleCookie, CookieError
import base64
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import time
from urllib.parse import quote

from PIL import Image
from cryptography.exceptions import InvalidTag
import core
import auth
from auth import vault
from mind import MindEngine
from mind.runtime import ModelUnavailable

VERSION='0.9.4'
ROOT='/api/v3'
ID=r'([0-9a-fA-F-]{36})'

class Failure(Exception):
    def __init__(self,status,code,message):
        self.status,self.code,self.message=status,code,message


def db():
    with core.db():
        pass
    conn=sqlite3.connect(core.DB_PATH,timeout=15)
    return conn


def valid_write(h):
    origin=h.headers.get('Origin')
    if origin or h.headers.get('Cookie') or h.headers.get('Sec-Fetch-Site'):
        expected=os.environ.get('CHELSY_PUBLIC_ORIGIN','https://'+h.headers.get('Host','')).rstrip('/')
        if origin!=expected or h.headers.get('X-Chelsy-Request')!='cabinet':
            h.reply(403,{'error':'origin_rejected','message':'Откройте кабинет на HTTPS-адресе Host.'})
            return False
    return True


def body(h,limit=70000):
    try: size=int(h.headers['Content-Length'])
    except (TypeError,ValueError): raise Failure(411,'length_required','Требуется Content-Length.')
    if size<0 or size>limit: raise Failure(413,'too_large','Превышен размер запроса.')
    if h.headers.get_content_type()!='application/json': raise Failure(415,'unsupported','Требуется application/json.')
    data=json.loads(h.rfile.read(size))
    if not isinstance(data,dict): raise ValueError()
    return data


def cookies(h):
    jar=SimpleCookie()
    try: jar.load(h.headers.get('Cookie',''))
    except CookieError: return {}
    return {name:item.value for name,item in jar.items()}


def send(h,status,payload,headers=()):
    data=json.dumps(payload,ensure_ascii=False).encode()
    binary(h,status,data,'application/json; charset=utf-8',headers)


def binary(h,status,data,mime,headers=()):
    h.send_response(status)
    for k,v in [('Content-Type',mime),('Content-Length',str(len(data))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),*headers]:
        h.send_header(k,v)
    h.end_headers()
    h.wfile.write(data)


def session_reply(h,user,tokens):
    if h.headers.get('X-Chelsy-Request')=='cabinet':
        headers=[('Set-Cookie',f'chelsy_{kind}={tokens[kind+"_token"]}; Path={path}; Secure; HttpOnly; SameSite=Strict; Max-Age={tokens[kind+"_expires_in"]}') for kind,path in [('access','/'),('refresh',ROOT+'/auth')]]
        send(h,200,{'user':user},headers)
    else:
        h.reply(200,{'user':user,**tokens})


def active(h,conn):
    token=h.headers.get('Authorization','').removeprefix('Bearer ') or cookies(h).get('chelsy_access','')
    session=auth.resolve_access_token(conn,token)
    conn.commit()
    if not session: raise Failure(401,'auth_required','Войдите снова.')
    uid=session['user_id']
    user=auth.get_user(conn,uid)
    if not user or user['status']!='active': raise Failure(401,'auth_required','Войдите снова.')
    try: key=vault.recover(conn,session['session_id'],uid,token)
    except (ValueError,InvalidTag): raise Failure(401,'login_required','Для открытия ключа войдите снова.')
    user['must_change_password']=bool(conn.execute('SELECT 1 FROM required_password_change WHERE user_id=?',(uid,)).fetchone())
    return user,session['session_id'],key


def login(h,conn):
    data=body(h)
    email,password=data.get('email'),data.get('password')
    if not isinstance(email,str) or not isinstance(password,str) or len(email)>254 or len(password)>128:
        raise Failure(401,'auth_error','Неверный email или пароль.')
    user=auth.authenticate_user(conn,email,password,source=h.client_address[0])
    key=vault.unlock(conn,user['id'],password)
    tokens=auth.create_session(conn,user['id'],is_admin=user['is_admin'],device_label=str(data.get('device_label','client'))[:120],user_agent=h.headers.get('User-Agent',''),source_ip=h.client_address[0])
    vault.bind(conn,tokens,user['id'],key)
    conn.commit()
    user['must_change_password']=bool(conn.execute('SELECT 1 FROM required_password_change WHERE user_id=?',(user['id'],)).fetchone())
    session_reply(h,user,tokens)


def refresh(h,conn):
    data=body(h)
    secret=data.get('refresh_token') or cookies(h).get('chelsy_refresh','')
    try:
        tokens=auth.refresh_session(conn,secret)
        uid=tokens.pop('user_id')
        tokens.pop('is_admin')
        key=vault.recover(conn,tokens['session_id'],uid,secret,refresh=True)
        vault.bind(conn,tokens,uid,key)
    except (ValueError,InvalidTag):
        conn.commit()  # preserve revocation on reuse
        raise Failure(401,'invalid_refresh','Сессия истекла. Войдите снова.')
    conn.commit()
    session_reply(h,auth.get_user(conn,uid),tokens)


def facts(conn,uid,key):
    return [{'id':fid,'text':vault.open_json(key,box,fid)} for fid,box in conn.execute('SELECT id,payload FROM private_facts WHERE user_id=? ORDER BY rowid DESC LIMIT 100',(uid,))]


def history(conn,uid,key):
    rows=conn.execute('SELECT id,created,payload,favorite FROM private_history WHERE user_id=? ORDER BY created DESC',(uid,))
    return [dict(id=rid,created=created,favorite=bool(fav),**vault.open_json(key,payload,rid)) for rid,created,payload,fav in rows]


def tasks(conn,uid):
    return [dict(zip(('id','kind','status','progress','error','created'),row)) for row in conn.execute('SELECT id,kind,status,progress,error,created FROM mind_tasks WHERE user_id=? ORDER BY created DESC LIMIT 100',(uid,))]


def avatar(h,conn,user,key):
    data=body(h,limit=1400000)
    image=Image.open(io.BytesIO(base64.b64decode(data['image'],validate=True)))
    if image.format not in ('JPEG','PNG','WEBP') or image.width*image.height>4000000: raise ValueError()
    image.thumbnail((384,384))
    buf=io.BytesIO()
    image.convert('RGB').save(buf,format='JPEG',quality=85)
    uid=user['id']
    encoded=vault.seal(key,base64.b64encode(buf.getvalue()).decode(),uid+'/avatar')
    conn.execute('UPDATE auth_users SET avatar_path=? WHERE id=?',(encoded,uid))
    conn.commit()
    h.reply(200,{'ok':True})


def handle_public(h,method,path):
    if not path.startswith(ROOT+'/'): return False
    with closing(db()) as conn:
        try:
            if method=='GET' and path==ROOT+'/health':
                h.reply(200,dict(service='Chelsy AI Host',version=VERSION,ok=True,auth='own'))
            elif method=='POST' and path==ROOT+'/auth/login': login(h,conn)
            elif method=='POST' and path==ROOT+'/auth/refresh': refresh(h,conn)
            elif path==ROOT+'/auth/register':
                raise Failure(403,'registration_disabled','Аккаунты создаёт владелец Host. Почтовая регистрация отключена.')
            else: private(h,conn,method,path.removeprefix(ROOT))
        except Failure as e: h.reply(e.status,{'error':e.code,'message':e.message})
        except auth.AuthError as e: h.reply(401 if path.endswith('/auth/login') else 400,{'error':'auth_error','message':str(e)})
        except ModelUnavailable as e: h.reply(503,{'error':'model_unavailable','message':str(e)})
        except (PermissionError,LookupError): h.reply(404,{'error':'not_found'})
        except InterruptedError: h.reply(409,{'error':'cancelled','message':'Задача отменена.'})
        except RuntimeError as e: h.reply(429,{'error':'busy','message':str(e)})
        except (ValueError,TypeError,AttributeError,Image.DecompressionBombError): h.reply(400,{'error':'invalid','message':'Проверьте параметры или структуру результата модели.'})
        except (OSError,sqlite3.Error,InvalidTag) as e:
            if not isinstance(e,(BrokenPipeError,ConnectionResetError)):
                h.reply(503,{'error':'storage_error','message':'Операция не завершена. Проверьте состояние Host.'})
    return True


handle_authed=handle_public


def private(h,conn,method,path):
    user,sid,key=active(h,conn)
    uid=user['id']
    user['has_avatar']=bool(user.pop('avatar_path',''))
    engine=MindEngine(conn,Path(core.DATA)/'artifacts',key=key)
    action=(method,path)
    if user['must_change_password'] and path not in ('/me','/me/password','/auth/logout'):
        raise Failure(403,'change_password','Сначала измените первоначальный пароль в разделе безопасности.')
    if action==('GET','/me'):
        return h.reply(200,{'user':user,'version':VERSION})
    if action==('POST','/me'):
        data=body(h)
        if 'locale' in data and data['locale'] not in ('ru','en'): raise ValueError()
        if 'timezone' in data and not isinstance(data['timezone'],str): raise ValueError()
        fields={k:v for k,v in data.items() if k in ('locale','timezone','display_name','memory_enabled')}
        result=auth.update_profile(conn,uid,**fields)
        result.pop('avatar_path',None)
        conn.commit()
        return h.reply(200,{'user':result})
    if action==('POST','/me/avatar'): return avatar(h,conn,user,key)
    if action==('GET','/me/avatar'):
        box=conn.execute('SELECT avatar_path FROM auth_users WHERE id=?',(uid,)).fetchone()[0]
        if not box: raise LookupError()
        return binary(h,200,base64.b64decode(vault.open_json(key,box,uid+'/avatar')),'image/jpeg')
    if action==('POST','/me/password'):
        data=body(h)
        auth.change_password(conn,uid,data.get('current_password',''),data.get('new_password',''))
        conn.execute('DELETE FROM required_password_change WHERE user_id=?',(uid,))
        auth.revoke_all_sessions(conn,uid)
        conn.commit()
        return h.reply(200,{'ok':True,'login_required':True})
    if action==('POST','/me/email'):
        from auth import mail
        data=body(h)
        if data.get('code'):
            mail.confirm(conn,uid,data.get('password',''),data['code'])
            return h.reply(200,{'changed':True})
        mail.request(conn,uid,data.get('password',''),data.get('new_email',''))
        return h.reply(202,{'confirmation_required':True})
    if action==('POST','/auth/logout'):
        auth.revoke_session(conn,sid,uid)
        conn.commit()
        return send(h,200,{'ok':True},[('Set-Cookie',f'chelsy_{kind}=; Path={p}; Secure; HttpOnly; SameSite=Strict; Max-Age=0') for kind,p in [('access','/'),('refresh',ROOT+'/auth')]])
    if action==('GET','/me/sessions'): return h.reply(200,{'sessions':auth.list_sessions(conn,uid)})
    if method=='DELETE' and (path=='/me/sessions' or path.startswith('/me/sessions/')):
        count=auth.revoke_all_sessions(conn,uid,except_id=sid) if path=='/me/sessions' else auth.revoke_session(conn,path.rsplit('/',1)[-1],uid)
        conn.commit()
        return h.reply(200,{'revoked':count})
    if action==('GET','/cabinet/overview'):
        import ollama_client
        files,size=conn.execute('SELECT count(*),coalesce(sum(size_bytes),0) FROM mind_artifacts WHERE user_id=?',(uid,)).fetchone()
        return h.reply(200,dict(host={'version':VERSION,'ollama':ollama_client.available(),'runtime':'PEFT' if os.getenv('CHELSY_LOCAL_BASE') else 'Ollama'},tasks_active=sum(t['status'] in ('queued','running') for t in tasks(conn,uid)),files_count=files,files_bytes=size,quota_mb_used=round(size/1048576,2),quota_mb_limit=user['quota_mb_limit']))
    if action==('POST','/mind/run'):
        data=body(h)
        message=data.get('message',data.get('text',''))
        if not isinstance(message,str) or not 0<len(message.strip())<=8000: raise ValueError()
        result=engine.handle(uid,message.strip(),idempotency_key=str(data.get('idempotency_key','')),source_artifact=data.get('source_artifact'))
        active(h,conn)
        return h.reply(200,asdict(result))
    if action==('GET','/memory'):
        return h.reply(200,{'facts':facts(conn,uid,key)})
    if action==('POST','/memory'):
        import uuid
        value=body(h).get('text')
        if not isinstance(value,str) or not 1<=len(value.strip())<=2000: raise ValueError()
        if conn.execute('SELECT count(*) FROM private_facts WHERE user_id=?',(uid,)).fetchone()[0]>=100: raise ValueError()
        fid=str(uuid.uuid4())
        conn.execute('INSERT INTO private_facts VALUES(?,?,?)',(fid,uid,vault.seal(key,value.strip(),fid)))
        conn.commit()
        return h.reply(201,{'id':fid})
    fact=re.fullmatch('/memory/'+ID,path)
    if method=='DELETE' and fact:
        cur=conn.execute('DELETE FROM private_facts WHERE id=? AND user_id=?',(fact[1],uid))
        conn.commit()
        if not cur.rowcount: raise LookupError()
        return h.reply(200,{'deleted':True})
    if action==('GET','/tasks'): return h.reply(200,{'tasks':tasks(conn,uid)})
    task=re.fullmatch('/tasks/'+ID+'/(cancel|repeat)',path)
    if method=='POST' and task:
        tid,op=task.groups()
        if op=='cancel': return h.reply(200,{'cancelled':engine.cancel_task(uid,tid)})
        row=conn.execute('SELECT params_json FROM mind_tasks WHERE user_id=? AND id=?',(uid,tid)).fetchone()
        if not row: raise LookupError()
        data=body(h)
        stored=vault.open_json(key,row[0],tid)
        message,source=(stored['text'],stored.get('source_artifact')) if isinstance(stored,dict) else (stored,None)
        return h.reply(200,asdict(engine.handle(uid,message,source_artifact=source,idempotency_key=str(data.get('idempotency_key','')))))
    if action==('GET','/history'): return h.reply(200,{'history':history(conn,uid,key)})
    item=re.fullmatch('/history/'+ID,path)
    if item and method in ('POST','DELETE'):
        if method=='POST':
            cur=conn.execute('UPDATE private_history SET favorite=? WHERE user_id=? AND id=?',(bool(body(h).get('favorite')),uid,item[1]))
        else:
            cur=conn.execute('DELETE FROM private_history WHERE user_id=? AND id=?',(uid,item[1]))
            if cur.rowcount: conn.execute("DELETE FROM mind_tasks WHERE id=? AND user_id=? AND status='done'",(item[1],uid))
        conn.commit()
        if not cur.rowcount: raise LookupError()
        return h.reply(200,{'ok':True})
    if action==('GET','/export'):
        return h.reply(200,{'profile':user,'memory':facts(conn,uid,key),'history':history(conn,uid,key),'artifacts':engine.list_artifacts(uid),'tasks':tasks(conn,uid)})
    if action==('POST','/me/deletion'):
        if user['is_admin']: raise Failure(409,'replace_admin','Сначала выполните совместную замену администратора.')
        data=body(h)
        auth.authenticate_user(conn,user['email'],data.get('password',''),source=h.client_address[0])
        conn.execute('INSERT OR IGNORE INTO deletion_requests VALUES(?,?)',(uid,datetime.now(timezone.utc).isoformat()))
        conn.commit()
        return h.reply(202,{'requested':True})
    if action==('GET','/artifacts'): return h.reply(200,{'artifacts':engine.list_artifacts(uid)})
    item=re.fullmatch('/artifacts/'+ID+'(?:/(download))?',path)
    if item and method in ('GET','DELETE'):
        art=engine.get_artifact(uid,item[1])
        if method=='DELETE':
            conn.execute('DELETE FROM mind_artifacts WHERE id=? AND user_id=?',(item[1],uid))
            conn.commit()
            Path(art['storage_path']).unlink(missing_ok=True)
            return h.reply(200,{'deleted':True})
        if item[2]:
            return binary(h,200,engine.read(art),art['mime'],[('Content-Disposition',"attachment; filename*=UTF-8''"+quote(art['filename'],safe=''))])
        art.pop('storage_path')
        return h.reply(200,{'artifact':art})
    if path.startswith('/admin/'):
        if not user['is_admin']: raise Failure(403,'forbidden','Нужны права администратора.')
        if action in (('POST','/admin/replacements'),('POST','/admin/replacements/approve')):
            from auth.administrators import change
            data=body(h)
            proposal=data.get('id') if path.endswith('/approve') else None
            if path.endswith('/approve') and not proposal: raise ValueError()
            pid=change(conn,uid,data.get('old',''),data.get('new',''),str(data.get('reason','')),proposal)
            return h.reply(200,{'id':pid,'status':'approved' if proposal else 'pending'})
        if action==('GET','/admin/users'): return h.reply(200,{'users':auth.list_users_admin(conn)})
        if action==('POST','/admin/users'):
            data=body(h)
            new=auth.create_user(conn,data.get('email',''),data.get('password',''),created_by=uid)
            conn.execute('INSERT INTO required_password_change VALUES(?)',(new['id'],))
            conn.commit()
            return h.reply(201,{'user':new})
        item=re.fullmatch('/admin/users/'+ID+'/status',path)
        if item and method=='POST':
            data=body(h)
            auth.set_user_status(conn,uid,item[1],data.get('status'),str(data.get('reason','')))
            if data.get('status')!='active': auth.revoke_all_sessions(conn,item[1])
            conn.commit()
            return h.reply(200,{'ok':True})
        if action==('POST','/admin/stop'):
            import lifecycle,uuid
            if h.client_address[0] not in ('127.0.0.1','::1') or h.headers.get('X-Forwarded-For'):raise Failure(403,'local_only','Требуется локальная панель.')
            data=body(h)
            if data.get('confirm') is not True:raise ValueError()
            conn.execute('INSERT INTO auth_audit VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),datetime.now(timezone.utc).isoformat(),uid,'host.stop','host','host','ok','{}'))
            conn.commit()
            h.reply(202,{'stopping':True,'deadline_seconds':25})
            lifecycle.stop(h.server)
            return
        if action==('GET','/admin/status'):
            import lifecycle
            import ollama_client
            return h.reply(200,dict(version=VERSION,resources=lifecycle.stats(core.DATA),ollama=ollama_client.available(),active_users=conn.execute("SELECT count(*) FROM auth_users WHERE status='active'").fetchone()[0],active_sessions=conn.execute('SELECT count(*) FROM auth_sessions WHERE revoked=0 AND access_expires>?',(time.time(),)).fetchone()[0],queue_len=conn.execute("SELECT count(*) FROM mind_tasks WHERE status IN ('queued','running')").fetchone()[0]))
        if action==('GET','/admin/errors'):
            rows=conn.execute("SELECT updated,error FROM mind_tasks WHERE status='failed' ORDER BY updated DESC LIMIT 100")
            return h.reply(200,{'errors':[{'at':at,'code':code,'module':'mind','message':'Ошибка задачи'} for at,code in rows]})
    raise LookupError()
