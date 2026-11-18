"""Import an authorized, offline JSON export of Supabase identities into a staged database."""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import uuid
from datetime import datetime,timezone

import migrations
from auth.accounts import EMAIL_RE

def transfer(conn,rows):
    now=datetime.now(timezone.utc).isoformat()
    imported=0
    for row in rows:
        uid=str(uuid.UUID(row['id']))
        email=row['email'].strip().lower()
        hashed=row.get('encrypted_password','')
        if not EMAIL_RE.fullmatch(email) or not re.fullmatch(r'\$2[aby]\$(?:0[4-9]|1[0-4])\$[./A-Za-z0-9]{53}',hashed):
            raise ValueError('Экспорт должен содержать UUID, email и поддерживаемый bcrypt-хеш. Перенос отменён.')
        old=conn.execute('SELECT id,email,legacy_supabase_id FROM auth_users WHERE id=? OR email=?',(uid,email)).fetchall()
        if old:
            if old!=[(uid,email,uid)]: raise ValueError('Конфликт идентификаторов. Перенос отменён.')
            continue
        conn.execute("INSERT INTO auth_users(id,email,password_hash,display_name,role,status,created,updated,email_verified,created_by,legacy_supabase_id) VALUES(?,?,?,?,'user','active',?,?,?,'offline-import',?)",(uid,email,hashed,email.split('@')[0],now,now,int(bool(row.get('email_confirmed_at'))),uid))
        for table in ('messages','conversations','personal_memory','user_settings','pending_memory','cloud_imported','cloud_origin'):
            conn.execute(f'UPDATE {table} SET username=? WHERE username=?',('u:'+uid,'sb:'+uid))
        conn.execute('INSERT INTO auth_legacy_map VALUES(?,?,?)',('sb:'+uid,uid,'offline-bcrypt-v1'))
        imported+=1
    return imported

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--source-db',type=Path,required=True)
    p.add_argument('--accounts',type=Path,required=True)
    p.add_argument('--staged-db',type=Path,required=True)
    args=p.parse_args()
    if not args.source_db.is_file() or args.staged_db.exists(): p.error('Нужны существующая исходная БД и новый путь результата.')
    rows=json.loads(args.accounts.read_text(encoding='utf-8-sig'))
    import tempfile
    from contextlib import closing
    import os
    with tempfile.TemporaryDirectory(dir=args.staged_db.parent) as tmp:
        dest=Path(tmp)/'staged.db'
        with closing(sqlite3.connect(args.source_db.resolve().as_uri()+'?mode=ro',uri=True)) as src,closing(sqlite3.connect(dest)) as dst:
            src.backup(dst)
        migrations.migrate(dest)
        with closing(sqlite3.connect(dest)) as conn,conn:
            before=conn.execute('SELECT count(*) FROM messages').fetchone()
            imported=transfer(conn,rows)
            assert before==conn.execute('SELECT count(*) FROM messages').fetchone()
            if conn.execute('PRAGMA integrity_check').fetchone()!=('ok',): raise ValueError('Повреждённая БД')
        os.link(dest,args.staged_db)
        print(f'Перенесено аккаунтов: {imported}. Сообщений: {before[0]}.')
if __name__=='__main__': main()
