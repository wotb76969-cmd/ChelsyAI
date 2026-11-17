"""Chelsy Host Admin Panel 0.9.4 (ADM-02) — local Tk UI, no private user content.

Run: python admin_panel.py
Remote admin UI is OFF by default.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

HOST = os.environ.get('CHELSY_ADMIN_HOST', 'http://127.0.0.1:8787').rstrip('/')


class Api:
    def __init__(self):
        self.access = ''
        self.refresh = ''
        self.user = None

    def call(self, method, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        headers = {'Accept': 'application/json'}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        if self.access:
            headers['Authorization'] = 'Bearer ' + self.access
        req = Request(HOST + path, data=data, headers=headers, method=method)
        with urlopen(req, timeout=20) as resp:
            return json.load(resp)

    def login(self, email, password):
        result = self.call('POST', '/api/v3/auth/login', {
            'email': email, 'password': password, 'device_label': 'admin-panel',
        })
        if not result.get('user', {}).get('is_admin'):
            raise PermissionError('Нужен административный аккаунт')
        self.access = result['access_token']
        self.refresh = result['refresh_token']
        self.user = result['user']
        return self.user


class AdminApp:
    def __init__(self, root):
        self.root = root
        self.api = Api()
        root.title('Chelsy AI · Панель Host 0.9.4')
        root.geometry('920x640')
        root.configure(bg='#0B0C20')
        self._login_ui()

    def _login_ui(self):
        frame = ttk.Frame(self.root, padding=24)
        frame.pack(expand=True)
        ttk.Label(frame, text='Вход администратора').grid(row=0, column=0, columnspan=2, pady=8)
        ttk.Label(frame, text='Email').grid(row=1, column=0, sticky='e')
        ttk.Label(frame, text='Пароль').grid(row=2, column=0, sticky='e')
        self.email = tk.StringVar()
        self.password = tk.StringVar()
        ttk.Entry(frame, textvariable=self.email, width=40).grid(row=1, column=1, pady=4)
        ttk.Entry(frame, textvariable=self.password, show='*', width=40).grid(row=2, column=1, pady=4)
        ttk.Button(frame, text='Войти', command=self._do_login).grid(row=3, column=1, sticky='e', pady=12)
        ttk.Label(frame, text=f'Host: {HOST}\nАдминистратор не видит чаты и файлы пользователей.',
                  wraplength=420).grid(row=4, column=0, columnspan=2)

    def _do_login(self):
        try:
            self.api.login(self.email.get().strip(), self.password.get())
        except PermissionError as exc:
            messagebox.showerror('Отказ', str(exc))
            return
        except Exception as exc:
            messagebox.showerror('Ошибка', f'Не удалось войти: {type(exc).__name__}')
            return
        for w in self.root.winfo_children():
            w.destroy()
        self._main_ui()

    def _main_ui(self):
        nb = ttk.Notebook(self.root)
        nb.pack(fill='both', expand=True, padx=8, pady=8)
        self.status_tab = ttk.Frame(nb)
        self.users_tab = ttk.Frame(nb)
        self.errors_tab = ttk.Frame(nb)
        nb.add(self.status_tab, text='Сервер')
        nb.add(self.users_tab, text='Аккаунты')
        nb.add(self.errors_tab, text='Ошибки')
        ttk.Button(self.status_tab, text='Обновить статус', command=self.refresh_status).pack(anchor='w', padx=8, pady=8)
        self.status_text = tk.Text(self.status_tab, height=20, bg='#12132a', fg='#E8E6F5', insertbackground='#E8E6F5')
        self.status_text.pack(fill='both', expand=True, padx=8, pady=8)
        ttk.Button(self.users_tab, text='Обновить список', command=self.refresh_users).pack(anchor='w', padx=8, pady=8)
        cols = ('email', 'role', 'status', 'quota', 'id')
        self.users = ttk.Treeview(self.users_tab, columns=cols, show='headings')
        for c, t in zip(cols, ('Email', 'Роль', 'Статус', 'Квота МБ', 'ID')):
            self.users.heading(c, text=t)
            self.users.column(c, width=140 if c != 'id' else 220)
        self.users.pack(fill='both', expand=True, padx=8, pady=8)
        btns = ttk.Frame(self.users_tab)
        btns.pack(fill='x', padx=8, pady=4)
        ttk.Button(btns, text='Заблокировать', command=lambda: self._set_status('blocked')).pack(side='left', padx=4)
        ttk.Button(btns, text='Разблокировать', command=lambda: self._set_status('active')).pack(side='left', padx=4)
        ttk.Label(self.users_tab, text='Названия личных документов и темы задач не показываются (SEC-04).').pack(anchor='w', padx=8)
        self.err_text = tk.Text(self.errors_tab, height=24, bg='#12132a', fg='#E8E6F5')
        self.err_text.pack(fill='both', expand=True, padx=8, pady=8)
        ttk.Button(self.errors_tab, text='Обновить', command=self.refresh_errors).pack(anchor='w', padx=8, pady=4)
        self.refresh_status()
        self.refresh_users()
        self.refresh_errors()

    def refresh_status(self):
        try:
            data = self.api.call('GET', '/api/v3/admin/status')
            self.status_text.delete('1.0', 'end')
            self.status_text.insert('end', json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as exc:
            messagebox.showerror('Статус', str(exc))

    def refresh_users(self):
        try:
            data = self.api.call('GET', '/api/v3/admin/users')
            for i in self.users.get_children():
                self.users.delete(i)
            for u in data.get('users', []):
                self.users.insert('', 'end', values=(
                    u['email'], u['role'], u['status'],
                    f"{u.get('quota_mb_used', 0)}/{u.get('quota_mb_limit', 512)}", u['id'],
                ))
        except Exception as exc:
            messagebox.showerror('Аккаунты', str(exc))

    def _set_status(self, status):
        sel = self.users.selection()
        if not sel:
            return
        uid = self.users.item(sel[0], 'values')[4]
        try:
            self.api.call('POST', f'/api/v3/admin/users/{uid}/status', {'status': status, 'reason': 'admin-panel'})
            self.refresh_users()
        except Exception as exc:
            messagebox.showerror('Статус', f'{type(exc).__name__}: операция отклонена или ошибка')

    def refresh_errors(self):
        try:
            data = self.api.call('GET', '/api/v3/admin/errors')
            self.err_text.delete('1.0', 'end')
            for e in data.get('errors', []):
                self.err_text.insert('end', f"{e['at']} [{e['code']}] {e['module']} {e['message']}\n")
        except Exception as exc:
            self.err_text.insert('end', f'Ошибка загрузки: {type(exc).__name__}\n')


def main():
    # Ensure migrations for local panel use same DB
    os.environ.setdefault('CHELSY_APPDATA', '1')
    root = tk.Tk()
    style = ttk.Style(root)
    try:
        style.theme_use('clam')
    except tk.TclError:
        pass
    AdminApp(root)
    root.mainloop()


if __name__ == '__main__':
    main()
