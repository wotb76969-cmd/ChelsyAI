"""Re-key a staged v6 artifact directory for its authenticated owner."""
import argparse
from contextlib import closing
from getpass import getpass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from auth import authenticate_user,vault
import migrations

def convert(root,email,password,apply):
    database=root/'chelsy.db'
    if not database.exists():raise ValueError('База не найдена.')
    migrations.migrate(database)
    with closing(sqlite3.connect(database)) as conn:
        u=authenticate_user(conn,email,password,source='local-migration')
        uid=u['id'];key=vault.unlock(conn,uid,password)
        items=conn.execute("SELECT id,task_id,format,title,filename,sha256 FROM mind_artifacts WHERE user_id=? AND storage_path NOT LIKE '%.enc'",(uid,)).fetchall()
        old_paths=[]
        for aid,tid,fmt,title,name,sha in items:
            uuid.UUID(aid);uuid.UUID(tid)
            owner=root/'artifacts'/uid
            src=(owner/tid/name).resolve()
            if src.parent!=(owner/tid).resolve() or not src.is_relative_to(owner.resolve()) or src.stat().st_size>25*1024**2:
                raise ValueError('Некорректная ссылка на файл.')
            raw=src.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=sha:raise ValueError('Хеш исходного файла не совпадает.')
            if not apply:continue
            target=owner/(aid+'.enc');nonce=os.urandom(12);blob=nonce+AESGCM(key).encrypt(nonce,raw,aid.encode())
            target.write_bytes(blob)
            if AESGCM(key).decrypt(nonce,target.read_bytes()[12:],aid.encode())!=raw:raise ValueError('Ошибка проверки копии.')
            meta=vault.seal(key,{'title':title,'filename':name,'preview':{'title':title,'format':fmt}},aid)
            conn.execute("UPDATE mind_artifacts SET title='',filename='',storage_path=?,meta_json=? WHERE id=? AND user_id=?",(str(Path(uid)/target.name),meta,aid,uid))
            old_paths.append(src)
        if apply:
            conn.commit()
            for src in old_paths:src.unlink()
        return len(items)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--staged-data',type=Path,required=True);p.add_argument('--email',required=True);p.add_argument('--apply',action='store_true')
    args=p.parse_args();print('Файлов обработано:',convert(args.staged_data,args.email,getpass(),args.apply))
