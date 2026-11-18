"""Authenticated offline copy of the data directory. Restore only to a new directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from getpass import getpass
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes

MAGIC=b'CHELSYBK1'
CHUNK=1024*1024

def key(password,salt):
    if len(password)<15: raise ValueError('Требуется отдельный пароль резервной копии от 15 символов.')
    return hashlib.scrypt(password.encode(),salt=salt,n=32768,r=8,p=1,maxmem=128*1024**2,dklen=32)

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def pack(src,dest,password):
    if not (src/'chelsy.db').is_file() or dest.exists() or dest.resolve().is_relative_to(src.resolve()): raise ValueError('Нужны исходная БД и новый файл вне каталога данных.')
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp=Path(tmp);db=tmp/'chelsy.db'
        with closing(sqlite3.connect((src/'chelsy.db').resolve().as_uri()+'?mode=ro',uri=True)) as a,closing(sqlite3.connect(db)) as b:a.backup(b)
        manifest={}
        with zipfile.ZipFile(tmp/'data.zip','w',zipfile.ZIP_DEFLATED) as z:
            for p in [db,*sorted(src.rglob('*'))]:
                if p.is_symlink(): raise ValueError('Символические ссылки требуют отдельной проверки.')
                if not p.is_file():continue
                rel='chelsy.db' if p==db else p.relative_to(src).as_posix()
                if p!=db and (rel in ('chelsy.db','chelsy.db-shm','chelsy.db-wal') or rel.startswith('backups/')):continue
                manifest[rel]=digest(p);z.write(p,rel)
            z.writestr('CHELSY-MANIFEST.json',json.dumps(manifest))
        salt=os.urandom(16);iv=os.urandom(12);header=MAGIC+salt+iv
        cipher=Cipher(algorithms.AES(key(password,salt)),modes.GCM(iv)).encryptor();cipher.authenticate_additional_data(header)
        encrypted=tmp/'backup'
        with (tmp/'data.zip').open('rb') as f,encrypted.open('wb') as out:
            out.write(header)
            for block in iter(lambda:f.read(CHUNK),b''):out.write(cipher.update(block))
            out.write(cipher.finalize());out.write(cipher.tag)
        os.link(encrypted,dest)

def restore(src,dest,password):
    if dest.exists(): raise ValueError('Для восстановления требуется новый каталог.')
    with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
        tmp=Path(tmp)
        with src.open('rb') as f,(tmp/'data.zip').open('wb') as out:
            header=f.read(len(MAGIC)+28)
            if not header.startswith(MAGIC): raise ValueError('Неизвестный архив.')
            f.seek(-16,2);end=f.tell();tag=f.read(16);f.seek(len(header))
            dec=Cipher(algorithms.AES(key(password,header[-28:-12])),modes.GCM(header[-12:],tag)).decryptor()
            dec.authenticate_additional_data(header)
            while f.tell()<end:out.write(dec.update(f.read(min(CHUNK,end-f.tell()))))
            out.write(dec.finalize())
        data=tmp/'data';data.mkdir()
        with zipfile.ZipFile(tmp/'data.zip') as z:
            manifest=json.loads(z.read('CHELSY-MANIFEST.json'))
            if set(z.namelist())!=set(manifest)|{'CHELSY-MANIFEST.json'}: raise ValueError('Манифест не совпадает.')
            for name,sha in manifest.items():
                rel=PurePosixPath(name)
                if '..' in rel.parts or rel.is_absolute() or '\\' in name or ':' in name: raise ValueError('Некорректный путь.')
                dst=data/rel;dst.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as f,dst.open('xb') as out:
                    for chunk in iter(lambda:f.read(CHUNK),b''):out.write(chunk)
                if digest(dst)!=sha:raise ValueError('Контрольная сумма не совпадает.')
        with closing(sqlite3.connect(data/'chelsy.db')) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise ValueError('Нарушена целостность базы.')
        data.rename(dest)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=('pack','restore'));p.add_argument('source',type=Path);p.add_argument('destination',type=Path)
    a=p.parse_args();pw=getpass('Пароль резервной копии: ')
    if a.action=='pack' and pw!=getpass('Повторите пароль: '):p.exit(2,'Пароли различаются.\n')
    (pack if a.action=='pack' else restore)(a.source,a.destination,pw)
