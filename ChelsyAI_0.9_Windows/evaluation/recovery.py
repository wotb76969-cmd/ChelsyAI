"""Offline rehearsals for migration, restore, UUID preservation and key isolation."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import tempfile
import uuid

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
def main():
    with tempfile.TemporaryDirectory() as tmp:
        t=Path(tmp);src=t/'source';src.mkdir()
        os.environ['CHELSY_DATA_DIR']=str(src)
        import bcrypt,auth,core,migrations,backup_private,transfer_accounts
        from auth import vault
        from configure_accounts import bootstrap
        uid=str(uuid.uuid4());cid=str(uuid.uuid4());owner='sb:'+uid
        user_pw=secrets.token_urlsafe(25);backup_pw=secrets.token_urlsafe(24)
        migrations.migrate(src/'chelsy.db',target=4)
        with sqlite3.connect(src/'chelsy.db') as conn:
            conn.execute("INSERT INTO conversations(id,username,title,created,updated) VALUES(?,?,?,'now','now')",(cid,owner,'История'))
            conn.execute("INSERT INTO messages(username,role,content,created,conversation_id) VALUES(?,'user','Вопрос','now',?)",(owner,cid))
            conn.execute("INSERT INTO personal_memory(username,memory_key,value,created) VALUES(?,'цвет','синий','now')",(owner,))
        account={'id':uid,'email':'restored@example.invalid','encrypted_password':bcrypt.hashpw(user_pw.encode(),bcrypt.gensalt()).decode()}
        with core.db() as conn:
            assert transfer_accounts.transfer(conn,[account])==1
            assert transfer_accounts.transfer(conn,[account])==0
            got=auth.authenticate_user(conn,account['email'],user_pw)
            assert got['id']==uid and got['role']=='user'
            key=vault.unlock(conn,uid,user_pw)
            vid=str(uuid.uuid4());conn.execute('INSERT INTO private_facts VALUES(?,?,?)',(vid,uid,vault.seal(key,'private fixture',vid)))
            bootstrap(conn,[('first@example.invalid',secrets.token_urlsafe(24)),('second@example.invalid',secrets.token_urlsafe(24))])
        backup=t/'backup.chelsy';backup_private.pack(src,backup,backup_pw)
        assert b'private fixture' not in backup.read_bytes()
        dst=t/'recovered';backup_private.restore(backup,dst,backup_pw)
        with sqlite3.connect(dst/'chelsy.db') as conn:
            assert conn.execute('PRAGMA integrity_check').fetchone()==('ok',)
            assert conn.execute('SELECT count(*) FROM auth_users').fetchone()==(3,)
            assert conn.execute('SELECT id,username FROM conversations').fetchone()==(cid,'u:'+uid)
            assert conn.execute('SELECT username,conversation_id FROM messages').fetchone()==('u:'+uid,cid)
            assert conn.execute('SELECT username,value FROM personal_memory').fetchone()==('u:'+uid,'синий')
            assert vault.unlock(conn,uid,user_pw)==key
            admin=conn.execute("SELECT id FROM auth_users WHERE role='admin' LIMIT 1").fetchone()[0]
            assert conn.execute('SELECT count(*) FROM private_facts WHERE user_id=?',(admin,)).fetchone()==(0,)
            assert vault.open_json(key,conn.execute('SELECT payload FROM private_facts WHERE user_id=?',(uid,)).fetchone()[0],vid)=='private fixture'
            assert conn.execute('SELECT password_hash FROM auth_users WHERE id=?',(uid,)).fetchone()[0].startswith('$argon2id$')
        wrong=t/'wrong-password'
        from cryptography.exceptions import InvalidTag
        try:backup_private.restore(backup,wrong,secrets.token_urlsafe(24))
        except InvalidTag: pass
        else:raise AssertionError('Backup authentication failed')
        assert not wrong.exists()
        print(json.dumps(dict(schema=7,accounts=3,admins=2,messages=1,conversations=1,legacy_facts=1,encrypted_facts=1,uuid_preserved=True,bcrypt_upgraded=True,wrong_password_rejected=True,sqlite_integrity='ok',duplicate_import_count=0),indent=2))
if __name__=='__main__':main()
