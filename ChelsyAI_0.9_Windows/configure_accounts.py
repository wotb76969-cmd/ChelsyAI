"""Local account provisioning. Credentials are entered only at a non-echoing prompt."""
import argparse
from getpass import getpass

import core
from auth import AuthError, create_user


def bootstrap(conn, profiles):
    if conn.execute("SELECT count(*) FROM auth_users WHERE role='admin'").fetchone()[0]:
        raise AuthError('Административные профили уже существуют. Первичная настройка остановлена.')
    if len(profiles)!=2 or profiles[0][1]==profiles[1][1]:
        raise AuthError('Укажите два разных профиля с отдельными паролями.')
    for email,password in profiles:
        create_user(conn,email,password,role='admin',created_by='local-bootstrap')


def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=['admins','user'])
    args=p.parse_args()
    profiles=[]
    for i in range(2 if args.action=='admins' else 1):
        email=input(f'Email {i+1}: ').strip()
        password=getpass('Пароль (от 15 символов): ')
        if password!=getpass('Повторите пароль: '):
            p.exit(2,'Пароли различаются.\n')
        profiles.append((email,password))
    try:
        with core.db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if args.action=='admins':
                bootstrap(conn,profiles)
            else:
                user=create_user(conn,*profiles[0],created_by='local-provision')
                conn.execute('INSERT INTO required_password_change VALUES(?)',(user['id'],))
    except AuthError as exc:
        p.exit(2,str(exc)+'\n')
    print('Учётные записи сохранены.')
if __name__=='__main__':
    main()
