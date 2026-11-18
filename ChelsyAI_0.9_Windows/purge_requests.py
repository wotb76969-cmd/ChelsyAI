"""Process user-confirmed deletion requests on a stopped Host. No interactive admin content access."""
import os
from pathlib import Path
import shutil
import uuid
from datetime import datetime,timezone
import core

def process():
    with core.db() as conn:
        conn.execute('BEGIN IMMEDIATE')
        users=conn.execute("SELECT r.user_id FROM deletion_requests r JOIN auth_users u ON u.id=r.user_id WHERE u.role='user'").fetchall()
        for uid, in users:
            uuid.UUID(uid)
            # Only paths built from a verified owner UUID, never caller-supplied filenames.
            directory=Path(core.DATA)/'artifacts'/uid
            if directory.exists():
                if directory.is_symlink():raise ValueError('Проверьте каталог артефактов.')
                shutil.rmtree(directory)
            for table in ('vault_sessions','used_refresh'):
                conn.execute(f'DELETE FROM {table} WHERE session_id IN (SELECT id FROM auth_sessions WHERE user_id=?)',(uid,))
            for table in ('mind_tasks','mind_artifacts','mind_router_log','private_history','private_facts','mail_changes','required_password_change','auth_sessions','auth_legacy_map','deletion_requests'):
                conn.execute(f'DELETE FROM {table} WHERE user_id=?',(uid,))
            for table in ('messages','conversations','personal_memory','pending_memory','cloud_origin','cloud_imported','user_settings'):
                conn.execute(f'DELETE FROM {table} WHERE username IN (?,?)',('u:'+uid,'sb:'+uid))
            conn.execute('DELETE FROM auth_users WHERE id=?',(uid,))
            conn.execute('INSERT INTO auth_audit VALUES(?,?,?,?,?,?,?,?)',(str(uuid.uuid4()),datetime.now(timezone.utc).isoformat(),'local-maintenance','user.erase','account',uid,'ok','{}'))
    return len(users)
if __name__=='__main__':print('Обработано запросов:',process())
