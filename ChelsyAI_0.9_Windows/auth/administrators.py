"""Atomic replacement with approval from both active administrators."""
import json
import uuid
from datetime import datetime,timezone,timedelta
from .accounts import AuthError,is_admin,get_user
from .sessions import revoke_all_sessions

def change(conn,actor,old,new,reason,proposal=None):
    conn.execute('BEGIN IMMEDIATE')
    if not is_admin(conn,actor): raise AuthError('Требуются права администратора.')
    now=datetime.now(timezone.utc)
    if proposal:
        r=conn.execute("SELECT proposer_id,payload_json,created FROM auth_admin_confirmations WHERE id=? AND action='replace' AND status='pending'",(proposal,)).fetchone()
        if not r or r[0]==actor or not is_admin(conn,r[0]) or now-datetime.fromisoformat(r[2])>timedelta(minutes=15):
            raise AuthError('Требуется действующая заявка второго администратора.')
        data=json.loads(r[1]);old,new,reason=data['old'],data['new'],data['reason']
    target=get_user(conn,new)
    if not is_admin(conn,old) or not target or target['role']!='user' or target['status']!='active' or not reason.strip():
        raise AuthError('Проверьте профили и причину.')
    if conn.execute('SELECT 1 FROM required_password_change WHERE user_id=?',(new,)).fetchone(): raise AuthError('Новый администратор должен сменить первоначальный пароль.')
    if not proposal:
        proposal=str(uuid.uuid4())
        conn.execute("INSERT INTO auth_admin_confirmations(id,action,payload_json,proposer_id,created) VALUES(?,'replace',?,?,?)",(proposal,json.dumps(dict(old=old,new=new,reason=reason[:200])),actor,now.isoformat()))
        action='admin.propose'
    else:
        conn.execute("UPDATE auth_users SET role='user' WHERE id=?",(old,))
        conn.execute("UPDATE auth_users SET role='admin' WHERE id=?",(new,))
        for uid in (old,new):revoke_all_sessions(conn,uid)
        conn.execute("UPDATE auth_admin_confirmations SET status='approved',confirmer_id=?,decided=? WHERE id=?",(actor,now.isoformat(),proposal))
        action='admin.approve'
    conn.execute("INSERT INTO auth_audit VALUES(?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),now.isoformat(),actor,action,'user',new,'ok',json.dumps(dict(old=old,reason=reason[:200]))))
    conn.commit()
    return proposal
