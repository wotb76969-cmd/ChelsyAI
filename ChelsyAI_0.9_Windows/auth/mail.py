"""Email change using the operator's optional SMTP submission server (implicit TLS)."""
from email.message import EmailMessage
import hashlib
import os
import secrets
import smtplib
import ssl
import time
from .accounts import AuthError,EMAIL_RE,change_email
from .passwords import verify_password
from .sessions import revoke_all_sessions

def request(conn,uid,pwd,address):
    smtp=os.environ.get('CHELSY_SMTP_HOST')
    sender=os.environ.get('CHELSY_MAIL_FROM')
    if not smtp or not sender: raise AuthError('Почта Host отключена. Для смены адреса требуется его подтверждение.')
    address=address.strip().lower()
    if not EMAIL_RE.fullmatch(address) or len(address)>254: raise AuthError('Проверьте email.')
    row=conn.execute('SELECT password_hash FROM auth_users WHERE id=?',(uid,)).fetchone()
    if not verify_password(row[0],pwd): raise AuthError('Проверьте текущий пароль.')
    now=time.time()
    conn.execute('BEGIN IMMEDIATE')
    recent=conn.execute('SELECT expires FROM mail_changes WHERE user_id=?',(uid,)).fetchone()
    if recent and recent[0]>now+540: raise AuthError('Повторите через минуту.')
    secret=secrets.token_urlsafe(18)
    msg=EmailMessage();msg['Subject']='Chelsy AI — подтверждение нового адреса';msg['From']=sender;msg['To']=address
    msg.set_content('Для смены адреса в открытом кабинете введите код в течение 10 минут:\n'+secret)
    try:
        with smtplib.SMTP_SSL(smtp,int(os.environ.get('CHELSY_SMTP_PORT','465')),context=ssl.create_default_context(),timeout=8) as mail:
            if os.getenv('CHELSY_SMTP_USER'):mail.login(os.environ['CHELSY_SMTP_USER'],os.environ['CHELSY_SMTP_PASSWORD'])
            mail.send_message(msg)
    except (OSError,smtplib.SMTPException) as exc:raise AuthError('Host не смог доставить письмо.') from exc
    conn.execute('INSERT OR REPLACE INTO mail_changes VALUES(?,?,?,?)',(uid,address,hashlib.sha256(secret.encode()).hexdigest(),now+600))
    conn.commit()

def confirm(conn,uid,pwd,secret):
    conn.execute('BEGIN IMMEDIATE')
    row=conn.execute('SELECT address,digest,expires FROM mail_changes WHERE user_id=?',(uid,)).fetchone()
    if not row or row[2]<time.time() or not secrets.compare_digest(row[1],hashlib.sha256(secret.encode()).hexdigest()): raise AuthError('Код недействителен.')
    change_email(conn,uid,pwd,row[0])
    conn.execute('UPDATE auth_users SET email_verified=1 WHERE id=?',(uid,))
    conn.execute('DELETE FROM mail_changes WHERE user_id=?',(uid,))
    revoke_all_sessions(conn,uid);conn.commit()
