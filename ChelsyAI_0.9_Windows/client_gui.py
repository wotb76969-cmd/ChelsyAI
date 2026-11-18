"""Chelsy AI Windows Client GUI (Tkinter, standard library only).

Layout mirrors the Desktop app: sidebar with new chat, history search,
conversations (favourites first), research and knowledge windows, sync
and profile; main chat with streaming answers, stop, regenerate, edit,
copy, sources, model choice, web toggle, text-file attachments and the
Chelsy Pulse status indicator.
"""
from __future__ import annotations

import json
import os
import queue
import re
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from tkinter import (BooleanVar, Canvas, END, Frame, Label, Listbox, StringVar, Text, Tk, Toplevel, filedialog,
                     messagebox, ttk)

import client_cache
import secure_store
from client_api import HostClient, HostError, Unauthorized, validate_host
from client_auth import AuthError, login as host_login, refresh as host_refresh, logout as host_logout

VERSION = '0.9.4'
BG = '#0B0C20'
PANEL = '#11132B'
PANEL2 = '#161937'
STROKE = '#262A52'
VIOLET = '#6D4AFF'
LAVENDER = '#A78BFA'
TEAL = '#21D9DA'
TEXT = '#ECEBFA'
MUTED = '#A3A6C8'
RAISED = '#1C2046'
SELECTED = '#2A2160'
USER_BUBBLE = '#231D4F'
CODE_BG = '#0E1029'
DANGER = '#FF8A65'
PULSE = {'ready': TEAL, 'generating': LAVENDER, 'searching': TEAL, 'checking': LAVENDER, 'syncing': VIOLET,
         'offline': '#FF8A65'}
# Inline Markdown: **bold**, *italic* / _italic_, `code`, [link](https://…), ISO dates (sources).
INLINE = re.compile(r'(\*\*[^*]+\*\*|(?<![\w*])\*[^*\s][^*]*\*(?![\w*])|(?<!\w)_[^_\s][^_]*_(?!\w)|`[^`]+`|'
                    r'\[[^\]]+\]\(https?://[^)\s]+\)|\b\d{4}-\d{2}-\d{2}\b)')
DATE = re.compile(r'\d{4}-\d{2}-\d{2}')
RESEARCH_STATUS = {'queued': 'в очереди', 'running': 'идёт', 'done': 'готово', 'error': 'ошибка', 'stopped': 'остановлено',
                   'fetched': 'на проверке', 'accepted': 'в базе', 'rejected': 'отклонено', 'duplicate': 'дубликат',
                   'skipped': 'пропущено', 'found': 'найдено'}
TEXT_EXT = ('.txt', '.md', '.py', '.json', '.csv', '.log', '.js', '.ts', '.html', '.css', '.yaml', '.yml', '.xml',
            '.ini', '.toml', '.dart', '.sql', '.java', '.c', '.cpp', '.cs', '.go', '.rs', '.sh', '.ps1', '.bat')


def asset(name):
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    return base / 'assets' / name


def settings_path():
    return Path(os.getenv('LOCALAPPDATA') or Path.home()) / 'ChelsyAI' / 'client.json'


class Session:
    """Own Host Auth session; refresh token persisted only with DPAPI (Windows)."""

    def __init__(self):
        self.access = None
        self.refresh_token = None
        self.email = ''
        self.host = ''
        self.lock = threading.Lock()
        self._access_expires = 0

    def login(self, email, password, remember, host=''):
        host = host or self.host
        if not host:
            raise AuthError('Сначала укажи адрес Host')
        result = host_login(host, email, password)
        with self.lock:
            self.host = host
            self.access = result['access_token']
            self.refresh_token = result.get('refresh_token')
            self.email = (result.get('user') or {}).get('email') or email
            self._access_expires = time.time() + int(result.get('access_expires_in') or 600) - 30
        if remember and self.refresh_token:
            secure_store.save(json.dumps({'refresh': self.refresh_token, 'host': host}))
        return result

    def resume(self):
        raw = secure_store.load()
        if not raw:
            return False
        try:
            data = json.loads(raw) if raw.startswith('{') else {'refresh': raw, 'host': self.host}
            token, host = data.get('refresh'), data.get('host') or self.host
            if not token or not host:
                return False
            result = host_refresh(host, token)
        except (AuthError, ValueError, TypeError):
            secure_store.clear()
            return False
        with self.lock:
            self.host = host
            self.access = result['access_token']
            self.refresh_token = result.get('refresh_token', token)
            self.email = ((result.get('user') or {}).get('email') or self.email)
            self._access_expires = time.time() + int(result.get('access_expires_in') or 600) - 30
        secure_store.save(json.dumps({'refresh': self.refresh_token, 'host': host}))
        return True

    def token(self, force_refresh=False):
        with self.lock:
            access, refresh, host, exp = self.access, self.refresh_token, self.host, self._access_expires
        if not access:
            raise Unauthorized('Нужно войти')
        if force_refresh or time.time() >= exp:
            if not refresh or not host:
                raise Unauthorized('Сессия истекла')
            result = host_refresh(host, refresh)
            with self.lock:
                self.access = result['access_token']
                self.refresh_token = result.get('refresh_token', refresh)
                self._access_expires = time.time() + int(result.get('access_expires_in') or 600) - 30
            if secure_store.load():
                secure_store.save(json.dumps({'refresh': self.refresh_token, 'host': host}))
            return self.access
        return access

    def logout(self):
        with self.lock:
            self.access = self.refresh_token = None
        secure_store.clear()


def _mix(a, b, t):
    """Blend two #rrggbb colours (t=0 → a, t=1 → b)."""
    a = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return '#%02x%02x%02x' % tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def _aurora_at(x):
    """Brand gradient violet → lavender → turquoise for x in [0, 1]."""
    x = x % 1.0
    return _mix(VIOLET, LAVENDER, x * 2) if x < 0.5 else _mix(LAVENDER, TEAL, (x - 0.5) * 2)


class AuroraBand(Canvas):
    """Signature move: Chelsy Pulse drawn as a 3 px aurora horizon on top of the composer.

    ready: still, dim gradient · generating: the gradient drifts · searching: a turquoise sweep ·
    syncing: lavender breathing · offline: flat coral. Animates only while Chelsy works.
    """
    SEGMENTS = 64

    def __init__(self, master, height=3, base=PANEL2):
        super().__init__(master, height=height, bg=base, highlightthickness=0, borderwidth=0)
        self.base = base
        self.state = 'ready'
        self.phase = 0.0
        self._job = None
        self.rects = [self.create_rectangle(0, 0, 0, height, width=0) for _ in range(self.SEGMENTS)]
        self.bind('<Configure>', lambda e: self._draw())

    def set(self, state):
        self.state = state
        if state in ('generating', 'searching', 'syncing', 'checking'):
            if self._job is None:
                self._tick()
        else:
            if self._job is not None:
                self.after_cancel(self._job)
                self._job = None
            self._draw()

    def _tick(self):
        self.phase = (self.phase + 0.02) % 1.0
        self._draw()
        self._job = self.after(60, self._tick)

    def _colour(self, x):
        state, t = self.state, self.phase
        if state == 'offline':
            return DANGER
        if state == 'ready':
            return _mix(self.base, _aurora_at(x * 0.999), 0.4)
        if state == 'searching':
            centre = t * 1.6 - 0.3
            return _mix(self.base, TEAL, max(0.15, 1 - abs(x - centre) * 4))
        if state == 'syncing':
            import math
            return _mix(self.base, LAVENDER, 0.45 + 0.4 * abs(math.sin(t * 2 * math.pi)))
        return _aurora_at(x * 0.5 + t)          # generating / checking: drifting aurora

    def _draw(self):
        width = max(1, self.winfo_width())
        h = int(self['height'])
        step = width / self.SEGMENTS
        for i, rect in enumerate(self.rects):
            self.coords(rect, i * step, 0, (i + 1) * step + 1, h)
            self.itemconfigure(rect, fill=self._colour(i / (self.SEGMENTS - 1)))


class PlaceholderEntry(ttk.Entry):
    """ttk.Entry with a muted placeholder (Tk has none built in)."""

    def __init__(self, master, placeholder, variable, **kw):
        super().__init__(master, textvariable=variable, **kw)
        self.placeholder, self.variable = placeholder, variable
        self._showing = False
        self.bind('<FocusIn>', lambda e: self._hide())
        self.bind('<FocusOut>', lambda e: self._show())
        self._show()

    def _show(self):
        if not self.variable.get():
            self._showing = True
            self.configure(style='Placeholder.TEntry')
            self.insert(0, self.placeholder)

    def _hide(self):
        if self._showing:
            self.delete(0, END)
            self.configure(style='TEntry')
            self._showing = False

    def value(self):
        return '' if self._showing else self.variable.get()


class Pulse(Canvas):
    def __init__(self, master, bg=BG):
        super().__init__(master, width=18, height=18, bg=bg, highlightthickness=0)
        self.state = 'ready'
        self.phase = 0
        self.ring = self.create_oval(2, 2, 16, 16, outline=TEAL, width=2)
        self.dot = self.create_oval(5, 5, 13, 13, fill=TEAL, outline='')
        self._animate()

    def set(self, state):
        self.state = state
        color = PULSE.get(state, TEAL)
        self.itemconfigure(self.dot, fill=color)
        self.itemconfigure(self.ring, outline=color)

    def _animate(self):
        if self.state in ('generating', 'searching', 'checking', 'syncing'):
            self.phase = (self.phase + 1) % 12
            r = 4 + self.phase * 0.45
            self.coords(self.ring, 9 - r, 9 - r, 9 + r, 9 + r)
            self.itemconfigure(self.ring, state='normal' if self.phase < 10 else 'hidden')
        else:
            self.coords(self.ring, 2, 2, 16, 16)
            self.itemconfigure(self.ring, state='hidden')
        self.after(90, self._animate)


class ChelsyClientApp:
    def __init__(self):
        if sys.platform == 'win32':
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(1)   # crisp text on scaled displays
            except Exception:
                pass
        self.root = Tk()
        self.root.title(f'Chelsy AI · Client {VERSION}')
        self.root.geometry('1180x780')
        self.root.minsize(760, 520)
        self.root.configure(bg=BG)
        try:
            self.root.iconbitmap(str(asset('chelsy.ico')))
        except Exception:
            pass
        self.events = queue.Queue()
        self.session = Session()
        self.client = None
        self.conversation = None
        self.conversations = []
        self.messages = []
        self.request_id = None
        self.busy = False
        self.answer_start = None
        try:
            self.saved = json.loads(settings_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.saved = {}
        self._style()
        self.login_frame = self._login_view()
        self.main_frame = None
        self.root.after(60, self._poll)
        if self.saved.get('host'):
            self._background(self._try_resume)

    # ------------------------------------------------------------------ style
    def _style(self):
        """Northern-lights theme on ttk 'clam': polar-night ground, tonal lifts, aurora only on actions."""
        style = ttk.Style(self.root)
        try:
            style.theme_use('clam')
        except Exception:
            pass
        base = ('Segoe UI', 10)
        style.configure('.', background=BG, foreground=TEXT, fieldbackground=PANEL2, bordercolor=STROKE,
                        lightcolor=STROKE, darkcolor=STROKE, troughcolor=BG, font=base, focuscolor=TEAL)
        style.configure('TFrame', background=BG)
        style.configure('Side.TFrame', background=PANEL)
        style.configure('TLabel', background=BG, foreground=TEXT)
        style.configure('Side.TLabel', background=PANEL, foreground=TEXT)
        style.configure('Muted.TLabel', background=BG, foreground=MUTED, font=('Segoe UI', 9))
        style.configure('SideMuted.TLabel', background=PANEL, foreground=MUTED, font=('Segoe UI Semibold', 9))
        style.configure('Title.TLabel', background=BG, foreground=TEXT, font=('Segoe UI Semibold', 14))
        # Default button: tonal lift, no border noise.
        style.configure('TButton', background=RAISED, foreground=TEXT, bordercolor=RAISED, borderwidth=0,
                        focusthickness=1, padding=(12, 7))
        style.map('TButton', background=[('pressed', SELECTED), ('active', '#252A5C'), ('disabled', PANEL)],
                  foreground=[('disabled', '#6B6F99')])
        # Primary action: the one aurora-coloured button per area (white on violet 5.15:1).
        style.configure('Accent.TButton', background=VIOLET, foreground='white', bordercolor=VIOLET,
                        font=('Segoe UI Semibold', 10), padding=(14, 7))
        style.map('Accent.TButton', background=[('pressed', '#5B3BE6'), ('active', '#7D5DFF'), ('disabled', '#3B2D86')],
                  foreground=[('disabled', '#C9C2F5')])
        style.configure('Stop.TButton', background=RAISED, foreground=DANGER, bordercolor=RAISED)
        style.map('Stop.TButton', background=[('active', '#2E1F3A'), ('disabled', PANEL2)],
                  foreground=[('disabled', '#6B6F99')])
        # Flat text buttons for secondary actions (message and conversation actions).
        style.configure('Flat.TButton', background=BG, foreground=LAVENDER, bordercolor=BG, padding=(8, 4))
        style.map('Flat.TButton', background=[('active', PANEL), ('pressed', RAISED)],
                  foreground=[('active', TEXT), ('disabled', '#6B6F99')])
        style.configure('Nav.TButton', background=PANEL, foreground=TEXT, bordercolor=PANEL, anchor='w', padding=(10, 7))
        style.map('Nav.TButton', background=[('active', RAISED), ('pressed', SELECTED)])
        style.configure('TCheckbutton', background=BG, foreground=TEXT, indicatorbackground=PANEL2,
                        indicatorforeground=TEAL)
        style.map('TCheckbutton', background=[('active', BG)], indicatorbackground=[('selected', VIOLET)],
                  indicatorforeground=[('selected', 'white')])
        style.configure('TCombobox', fieldbackground=PANEL2, background=PANEL2, foreground=TEXT, arrowcolor=LAVENDER,
                        bordercolor=STROKE, padding=4)
        style.map('TCombobox', fieldbackground=[('readonly', PANEL2)], foreground=[('readonly', TEXT)],
                  selectbackground=[('readonly', PANEL2)], selectforeground=[('readonly', TEXT)],
                  bordercolor=[('focus', LAVENDER)])
        self.root.option_add('*TCombobox*Listbox.background', PANEL2)
        self.root.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', SELECTED)
        style.configure('TEntry', fieldbackground=PANEL2, foreground=TEXT, insertcolor=LAVENDER, bordercolor=STROKE,
                        padding=6)
        style.map('TEntry', bordercolor=[('focus', LAVENDER)])
        style.configure('Placeholder.TEntry', fieldbackground=PANEL2, foreground=MUTED, bordercolor=STROKE, padding=6)
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28,
                        bordercolor=STROKE)
        style.map('Treeview', background=[('selected', SELECTED)], foreground=[('selected', TEXT)])
        style.configure('Treeview.Heading', background=PANEL2, foreground=MUTED, font=('Segoe UI Semibold', 9),
                        bordercolor=STROKE, relief='flat')
        style.map('Treeview.Heading', background=[('active', RAISED)])
        style.configure('Night.Vertical.TScrollbar', background=RAISED, troughcolor=BG, bordercolor=BG,
                        arrowcolor=MUTED, gripcount=0)
        style.map('Night.Vertical.TScrollbar', background=[('active', SELECTED)])
        style.configure('TSeparator', background=STROKE)

    # ------------------------------------------------------------------ login
    def _login_view(self):
        frame = ttk.Frame(self.root, padding=30)
        frame.place(relx=0.5, rely=0.5, anchor='center')
        try:
            from tkinter import PhotoImage
            self.logo = PhotoImage(file=str(asset('chelsy_logo_small.png'))).subsample(3, 3)
            Label(frame, image=self.logo, bg=BG).pack(pady=(0, 8))
        except Exception:
            pass
        ttk.Label(frame, text='Chelsy AI', style='Title.TLabel', font=('Segoe UI Semibold', 20)).pack()
        ttk.Label(frame, text='Войди email/паролем на свой Chelsy Host', style='Muted.TLabel').pack(pady=(0, 14))
        horizon = AuroraBand(frame, height=2, base=BG)
        horizon.configure(width=180)
        horizon.pack(pady=(0, 18))
        self.host_var = StringVar(value=self.saved.get('host', 'https://'))
        self.email_var = StringVar(value=self.saved.get('email', ''))
        self.password_var = StringVar()
        self.remember_var = BooleanVar(value=secure_store.supported())
        for label, var, show in (('Адрес Chelsy Host (HTTPS)', self.host_var, None), ('Email', self.email_var, None),
                                 ('Пароль', self.password_var, '•')):
            ttk.Label(frame, text=label, style='Muted.TLabel').pack(anchor='w')
            entry = ttk.Entry(frame, textvariable=var, show=show, width=46)
            entry.pack(fill='x', pady=(2, 10), ipady=4)
            entry.bind('<Return>', lambda e: self._login())
        remember = ttk.Checkbutton(frame, text='Запомнить вход (зашифровано Windows DPAPI)', variable=self.remember_var)
        remember.pack(anchor='w', pady=(0, 10))
        if not secure_store.supported():
            remember.state(['disabled'])
        self.login_button = ttk.Button(frame, text='Войти', style='Accent.TButton', command=self._login)
        self.login_button.pack(fill='x', ipady=3)
        self.login_status = ttk.Label(frame, text='', style='Muted.TLabel', wraplength=380)
        self.login_status.pack(pady=(10, 0))
        return frame

    def _remember(self, **values):
        self.saved.update(values)
        try:
            settings_path().parent.mkdir(parents=True, exist_ok=True)
            settings_path().write_text(json.dumps(self.saved), encoding='utf-8')
        except OSError:
            pass

    def _login(self):
        try:
            host = validate_host(self.host_var.get())
        except ValueError as exc:
            self.login_status.configure(text=str(exc))
            return
        email, password, remember = self.email_var.get().strip(), self.password_var.get(), self.remember_var.get()
        self.password_var.set('')
        self.login_button.state(['disabled'])
        self.login_status.configure(text='Вход…')

        def job():
            try:
                self.session.login(email, password, remember, host=host)
                self.events.put(('logged-in', host))
            except AuthError as exc:
                self.events.put(('login-error', 'Не удалось войти: проверь Host, email и пароль. (' + str(exc) + ')'))
        self._background(job)

    def _try_resume(self):
        try:
            host = validate_host(self.saved.get('host', ''))
        except ValueError:
            return
        if self.session.resume():
            self.events.put(('logged-in', host))

    # ------------------------------------------------------------------ main
    def _main_view(self):
        main = Frame(self.root, bg=BG)
        main.pack(fill='both', expand=True)
        side = ttk.Frame(main, style='Side.TFrame', padding=(14, 14, 14, 12), width=268)
        side.pack(side='left', fill='y')
        side.pack_propagate(False)
        head = ttk.Frame(side, style='Side.TFrame')
        head.pack(fill='x', pady=(0, 14))
        try:
            from tkinter import PhotoImage
            self.logo_small = PhotoImage(file=str(asset('chelsy_logo_small.png'))).subsample(6, 6)
            Label(head, image=self.logo_small, bg=PANEL).pack(side='left')
        except Exception:
            pass
        ttk.Label(head, text='  Chelsy AI', style='Side.TLabel', font=('Segoe UI Semibold', 14)).pack(side='left')
        ttk.Button(side, text='Новый чат', style='Accent.TButton', command=self.new_chat).pack(fill='x', pady=(0, 10))
        self.search_var = StringVar()
        search = PlaceholderEntry(side, 'Поиск по истории', self.search_var)
        search.pack(fill='x', ipady=4)
        search.bind('<KeyRelease>', lambda e: self._debounce_search())
        Frame(side, bg=PANEL, height=10).pack(fill='x')
        self.conv_list = Listbox(side, bg=PANEL, fg=TEXT, selectbackground=SELECTED, selectforeground=TEXT,
                                 highlightthickness=0, borderwidth=0, activestyle='none', font=('Segoe UI', 10))
        self.conv_list.pack(fill='both', expand=True)
        self.conv_list.bind('<<ListboxSelect>>', lambda e: self._open_selected())
        self.conv_list.bind('<Button-3>', self._conversation_menu)
        ttk.Separator(side).pack(fill='x', pady=(10, 8))
        for text, cmd in (('Исследования', self.open_research), ('База знаний', self.open_knowledge),
                          ('Синхронизировать', self.sync)):
            ttk.Button(side, text=text, style='Nav.TButton', command=cmd).pack(fill='x', pady=1)
        profile = ttk.Frame(side, style='Side.TFrame')
        profile.pack(fill='x', pady=(10, 0))
        initial = (self.session.email or '?')[:1].upper()
        badge = Canvas(profile, width=28, height=28, bg=PANEL, highlightthickness=0)
        badge.create_oval(1, 1, 27, 27, fill=VIOLET, outline='')
        badge.create_text(14, 14, text=initial, fill='white', font=('Segoe UI Semibold', 10))
        badge.pack(side='left')
        ttk.Label(profile, text=' ' + (self.session.email or 'аккаунт')[:24], style='Side.TLabel').pack(side='left')
        ttk.Button(profile, text='Выйти', style='Nav.TButton', command=self.logout).pack(side='right')

        content = ttk.Frame(main, padding=(20, 14, 20, 12))
        content.pack(side='left', fill='both', expand=True)
        top = ttk.Frame(content)
        top.pack(fill='x')
        self.title_label = ttk.Label(top, text='Новый чат', style='Title.TLabel')
        self.title_label.pack(side='left')
        for text, cmd in (('Удалить', self.delete_chat), ('Переименовать', self.rename_chat),
                          ('В избранное', self.toggle_favorite)):
            ttk.Button(top, text=text, style='Flat.TButton', command=cmd).pack(side='right')
        status = ttk.Frame(content)
        status.pack(fill='x', pady=(2, 0))
        self.pulse = Pulse(status)
        self.pulse.pack(side='left')
        self.status_label = Label(status, text='Подключение…', bg=BG, fg=MUTED, font=('Segoe UI', 9))
        self.status_label.pack(side='left', padx=(4, 0))

        # Bottom widgets are packed first so they stay visible on small or scaled screens.
        ttk.Label(content, text='Enter — отправить, Shift+Enter — новая строка. Ответы могут содержать ошибки.',
                  style='Muted.TLabel').pack(side='bottom', anchor='w', pady=(6, 0))
        opts = ttk.Frame(content)
        opts.pack(side='bottom', fill='x', pady=(6, 0))
        self.model_var = StringVar()
        self.model_box = ttk.Combobox(opts, textvariable=self.model_var, state='readonly', width=18)
        self.model_box.pack(side='left')
        self.web_var = BooleanVar(value=self.saved.get('web', True))
        ttk.Checkbutton(opts, text='Поиск в интернете', variable=self.web_var,
                        command=lambda: self._remember(web=self.web_var.get())).pack(side='left', padx=12)
        ttk.Button(opts, text='Прикрепить файл', style='Flat.TButton', command=self.attach).pack(side='left')
        ttk.Button(opts,text='Chelsy Mind · файлы',style='Flat.TButton',command=self.mind_window).pack(side='left')
        self.attachments = []
        self.attach_label = ttk.Label(opts, text='', style='Muted.TLabel')
        self.attach_label.pack(side='left', padx=8)

        compose = Frame(content, bg=PANEL2)
        compose.pack(side='bottom', fill='x')
        # Signature: the aurora horizon along the composer's top edge shows Chelsy's state.
        self.aurora = AuroraBand(compose)
        self.aurora.pack(fill='x', side='top')
        inner = Frame(compose, bg=PANEL2, padx=12, pady=8)
        inner.pack(fill='both', expand=True)
        buttons = Frame(inner, bg=PANEL2)
        buttons.pack(side='right', padx=(10, 0), fill='y')  # packed before the input so it keeps its width
        self.send_button = ttk.Button(buttons, text='Отправить', style='Accent.TButton', command=self.send, width=11)
        self.send_button.pack(side='top', fill='x', pady=(0, 4))
        self.stop_button = ttk.Button(buttons, text='Стоп', style='Stop.TButton', command=self.stop, width=11)
        self.stop_button.pack(side='top', fill='x')
        self.stop_button.state(['disabled'])

        self.input = Text(inner, height=3, wrap='word', bg=PANEL2, fg=TEXT, insertbackground=LAVENDER, borderwidth=0,
                          highlightthickness=0, font=('Segoe UI', 11), selectbackground=VIOLET, selectforeground='white')
        self.input.pack(side='left', fill='both', expand=True)
        self.input.bind('<Return>', self._enter)
        self.input.bind('<Shift-Return>', lambda e: None)
        actions = ttk.Frame(content)
        actions.pack(side='bottom', fill='x', pady=(0, 6))
        for text, cmd in (('Копировать ответ', self.copy_answer), ('Изменить последнее', self.edit_last),
                          ('Повторить ответ', self.regenerate)):
            ttk.Button(actions, text=text, style='Flat.TButton', command=cmd).pack(side='right')

        chat_frame = Frame(content, bg=BG)
        chat_frame.pack(fill='both', expand=True, pady=(12, 8))
        self.chat = Text(chat_frame, wrap='word', bg=BG, fg=TEXT, insertbackground=TEXT, borderwidth=0,
                         highlightthickness=0, font=('Segoe UI', 11), padx=18, pady=10, spacing1=2, spacing3=5,
                         selectbackground=VIOLET, selectforeground='white')
        scroll = ttk.Scrollbar(chat_frame, command=self.chat.yview, style='Night.Vertical.TScrollbar')
        self.chat.configure(yscrollcommand=scroll.set, state='disabled')
        scroll.pack(side='right', fill='y')
        self.chat.pack(side='left', fill='both', expand=True)
        self.chat.tag_configure('user', background=USER_BUBBLE, lmargin1=160, lmargin2=160, rmargin=8,
                                spacing1=10, spacing3=10, justify='right')
        try:  # Tk 8.6.6+: keep the margins night-coloured so the bubble is only as wide as its column
            self.chat.tag_configure('user', lmargincolor=BG, rmargincolor=BG)
        except Exception:  # noqa: BLE001 — older Tk: the bubble spans the full line, still readable
            pass
        self.chat.tag_configure('author', foreground=LAVENDER, font=('Segoe UI Semibold', 10), spacing1=16)
        self.chat.tag_configure('author_user', foreground=MUTED, font=('Segoe UI Semibold', 10), spacing1=16,
                                justify='right', rmargin=8)
        self.chat.tag_configure('bold', font=('Segoe UI Semibold', 11))
        self.chat.tag_configure('italic', font=('Segoe UI', 11, 'italic'))
        self.chat.tag_configure('heading', font=('Segoe UI Semibold', 13), spacing1=8)
        self.chat.tag_configure('code', font=('Consolas', 10), background=CODE_BG, foreground=TEXT,
                                lmargin1=24, lmargin2=24, rmargin=24)
        self.chat.tag_configure('inline', font=('Consolas', 10), background=RAISED)
        self.chat.tag_configure('link', foreground=LAVENDER, underline=True)
        self.chat.tag_configure('date', foreground=TEAL)
        self.chat.tag_configure('muted', foreground=MUTED, font=('Segoe UI', 9, 'italic'))
        self.chat.tag_configure('rule', foreground=STROKE)
        self.chat.bind('<Configure>', self._fit_turns, add='+')
        self.chat_avatar = None
        try:
            from tkinter import PhotoImage
            self.chat_avatar = PhotoImage(file=str(asset('chelsy_logo_small.png'))).subsample(8, 8)
        except Exception:  # noqa: BLE001 — a missing image must never block the chat
            self.chat_avatar = None
        self.chat.tag_bind('link', '<Button-1>', self._click_link)
        self.chat.tag_bind('link', '<Enter>', lambda e: self.chat.configure(cursor='hand2'))
        self.chat.tag_bind('link', '<Leave>', lambda e: self.chat.configure(cursor=''))
        return main

    def _conversation_menu(self, event):
        index = self.conv_list.nearest(event.y)
        conv = self._row_conversation(index)
        if conv is None:
            return
        self.conv_list.selection_clear(0, END)
        self.conv_list.selection_set(index)
        self._open_selected()
        from tkinter import Menu
        menu = Menu(self.root, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=SELECTED, activeforeground=TEXT,
                    borderwidth=0)
        menu.add_command(label='Убрать из избранного' if conv['favorite'] else 'В избранное', command=self.toggle_favorite)
        menu.add_command(label='Переименовать…', command=self.rename_chat)
        menu.add_separator()
        menu.add_command(label='Удалить', command=self.delete_chat)
        menu.tk_popup(event.x_root, event.y_root)

    # ------------------------------------------------------------------ helpers
    def _background(self, fn, *args):
        threading.Thread(target=fn, args=args, daemon=True).start()

    def _api(self, fn, *args, then=None, **kw):
        def job():
            try:
                result = fn(*args, **kw)
                self.events.put(('call', (then, result)))
            except Unauthorized:
                self.events.put(('unauthorized', None))
            except (HostError, AuthError, OSError) as exc:
                self.events.put(('error', str(exc)))
        self._background(job)

    def _set_status(self, state, text):
        self.pulse.set(state)
        if hasattr(self, 'aurora'):
            self.aurora.set(state)
        self.status_label.configure(text=text)

    def _search_query(self):
        value = self.search_var.get().strip()
        return '' if value == 'Поиск по истории' else value

    def _debounce_search(self):
        if hasattr(self, '_search_job'):
            self.root.after_cancel(self._search_job)
        self._search_job = self.root.after(350, self.load_conversations)

    def _enter(self, event):
        if event.state & 0x0001:     # Shift pressed: newline
            return None
        self.send()
        return 'break'

    # ------------------------------------------------------------------ rendering
    def _insert_markdown(self, text):
        in_code = False
        for line in text.split('\n'):
            if line.strip().startswith('```'):
                in_code = not in_code
                continue
            if in_code:
                self.chat.insert(END, line + '\n', 'code')
                continue
            if line.strip() == '---':
                self.chat.insert(END, '─' * 40 + '\n', 'rule')
                continue
            m = re.match(r'^(#{1,4})\s+(.*)', line)
            if m:
                self.chat.insert(END, m.group(2) + '\n', 'heading')
                continue
            for part in INLINE.split(line):
                if part.startswith('**') and part.endswith('**') and len(part) > 4:
                    self.chat.insert(END, part[2:-2], 'bold')
                elif len(part) > 2 and part[0] == part[-1] and part[0] in '*_' and part[1] not in ' *_':
                    self.chat.insert(END, part[1:-1], 'italic')
                elif DATE.fullmatch(part):
                    self.chat.insert(END, part, 'date')
                elif part.startswith('`') and part.endswith('`') and len(part) > 2:
                    self.chat.insert(END, part[1:-1], 'inline')
                elif part.startswith('[') and '](' in part:
                    label, url = part[1:-1].split('](', 1)
                    self.chat.insert(END, label, ('link', 'url:' + url))
                else:
                    self.chat.insert(END, part)
            self.chat.insert(END, '\n')

    def render(self, streaming_text=None):
        self.chat.configure(state='normal')
        self.chat.delete('1.0', END)
        if not self.messages and streaming_text is None:
            self.chat.insert(END, '\n\nПривет! Я Челси 💜\n', 'heading')
            self.chat.insert(END, 'Спрашивай, проси объяснить, помочь с кодом или изучить тему — я покажу источники '
                                  'и даты.\n\nНапример:\n', 'muted')
            for example in ('Объясни простыми словами, как работает Wi‑Fi', 'Найди свежие новости о Python',
                            'Изучи документацию FastAPI'):
                self.chat.insert(END, '  ' + example + '\n', ('link', 'example:' + example))
        for m in self.messages:
            if m['role'] == 'user':
                self.chat.insert(END, 'Ты\n', 'author_user')
                self.chat.insert(END, m['content'] + '\n', 'user')
            else:
                self._chelsy_author()
                self._insert_markdown(m['content'])
        if streaming_text is not None:
            self._chelsy_author()
            self._insert_markdown(streaming_text + ' ▍')
        self.chat.configure(state='disabled')
        self.chat.see(END)

    def _chelsy_author(self):
        """Chelsy's turn starts with her logo avatar, then the name."""
        if self.chat_avatar is not None:
            start = self.chat.index('end-1c')
            self.chat.image_create(END, image=self.chat_avatar, padx=0, align='center')
            self.chat.insert(END, '  Chelsy\n', 'author')
            self.chat.tag_add('author', start, 'end-1c')  # the avatar line keeps the turn spacing
        else:
            self.chat.insert(END, 'Chelsy\n', 'author')

    def _fit_turns(self, event=None):
        """The user's turn is a right-side bubble: it starts at ~38% of the chat width."""
        width = self.chat.winfo_width() if event is None else event.width
        if width > 1:
            margin = max(48, int(width * 0.38))
            self.chat.tag_configure('user', lmargin1=margin, lmargin2=margin)

    def _click_link(self, event):
        index = self.chat.index(f'@{event.x},{event.y}')
        for tag in self.chat.tag_names(index):
            if tag.startswith('example:'):
                self.input.delete('1.0', END)
                self.input.insert('1.0', tag[8:])
                self.input.focus_set()
                return
            if tag.startswith('url:https://'):
                webbrowser.open(tag[4:])

    # ------------------------------------------------------------------ data
    def _account(self):
        return self.session.email or self.saved.get('email', '')

    def _cached_conversations(self, query):
        """Host first; on network failure fall back to the local offline copy."""
        try:
            items = self.client.conversations(query)
            if not query:
                client_cache.save_conversations(self._account(), items)
            return items
        except Unauthorized:
            raise
        except HostError:
            items = client_cache.load_conversations(self._account(), query)
            self.events.put(('offline', 'Хост недоступен — показана сохранённая на этом ПК копия'))
            return items

    def _cached_messages(self, conversation_id):
        try:
            items = self.client.messages(conversation_id)
            client_cache.save_messages(self._account(), conversation_id, items)
            return items
        except Unauthorized:
            raise
        except HostError:
            items = client_cache.load_messages(self._account(), conversation_id)
            self.events.put(('offline', 'Хост недоступен — показана сохранённая копия диалога'))
            return items

    def load_conversations(self):
        if self.client:
            self._api(self._cached_conversations, self._search_query(), then='conversations')

    def _show_conversations(self, items):
        favs = [c for c in items if c['favorite']]
        rest = [c for c in items if not c['favorite']]
        self.conversations = favs + rest
        # Row map: None marks a group header row (not selectable).
        self.rows = []
        self.conv_list.delete(0, END)

        def header(text):
            self.conv_list.insert(END, text)
            self.conv_list.itemconfigure(END, fg=MUTED, selectbackground=PANEL, selectforeground=MUTED)
            self.rows.append(None)
        if favs:
            header('Избранное')
        for c in self.conversations:
            if rest and c is rest[0]:
                header('Недавние')
            self.conv_list.insert(END, '  ' + c['title'][:40])
            if c['favorite']:
                self.conv_list.itemconfigure(END, fg=LAVENDER)
            self.rows.append(c)
            if c['id'] == self.conversation:
                self.conv_list.selection_set(END)

    def _row_conversation(self, index):
        rows = getattr(self, 'rows', None)
        if rows is None:
            return self.conversations[index] if index < len(self.conversations) else None
        return rows[index] if 0 <= index < len(rows) else None

    def _open_selected(self):
        sel = self.conv_list.curselection()
        if not sel or self.busy:
            return
        conv = self._row_conversation(sel[0])
        if conv is None:                  # a group header
            self.conv_list.selection_clear(sel[0])
            return
        self.conversation = conv['id']
        self.title_label.configure(text=conv['title'][:70])
        self._api(self._cached_messages, conv['id'], then='messages')

    def new_chat(self):
        if self.busy:
            return
        self.conversation = None
        self.messages = []
        self.title_label.configure(text='Новый чат')
        self.conv_list.selection_clear(0, END)
        self.render()
        self.input.focus_set()

    def toggle_favorite(self):
        conv = next((c for c in self.conversations if c['id'] == self.conversation), None)
        if conv:
            self._api(self.client.update_conversation, conv['id'], favorite=not conv['favorite'], then='refresh')

    def rename_chat(self):
        if not self.conversation:
            return
        from tkinter import simpledialog
        title = simpledialog.askstring('Chelsy AI', 'Новое название чата:', parent=self.root)
        if title and title.strip():
            self.title_label.configure(text=title.strip()[:70])
            self._api(self.client.update_conversation, self.conversation, title=title.strip(), then='refresh')

    def delete_chat(self):
        if self.conversation and messagebox.askyesno('Chelsy AI', 'Удалить этот чат? (Он скрывается, данные на хосте сохраняются в резервной копии.)'):
            self._api(self.client.delete_conversation, self.conversation, then='refresh')
            self.new_chat()

    # ------------------------------------------------------------------ chat
    def attach(self):
        paths = filedialog.askopenfilenames(title='Текстовые файлы', filetypes=[('Текст и код', ' '.join('*' + e for e in TEXT_EXT))])
        self.attachments = []
        for p in paths[:4]:
            path = Path(p)
            if path.suffix.lower() not in TEXT_EXT:
                continue
            data = path.read_bytes()[:200_000]
            try:
                text = data.decode('utf-8')
            except UnicodeDecodeError:
                text = data.decode('cp1251', errors='replace')
            self.attachments.append({'name': path.name, 'text': text[:12000]})
        self.attach_label.configure(text=('Файлы: ' + ', '.join(a['name'] for a in self.attachments)) if self.attachments else '')

    def send(self, regenerate=False, edit_id=None, text=None):
        if self.busy or not self.client:
            return
        text = text if text is not None else self.input.get('1.0', END).strip()
        if not text and not self.attachments and not regenerate:
            return
        if not regenerate:
            self.input.delete('1.0', END)
            if edit_id is not None:
                idx = next((i for i, m in enumerate(self.messages) if m.get('id') == edit_id), len(self.messages))
                self.messages = self.messages[:idx]
            self.messages.append({'role': 'user', 'content': text})
        else:
            while self.messages and self.messages[-1]['role'] == 'assistant':
                self.messages.pop()
        attachments, self.attachments = self.attachments, []
        self.attach_label.configure(text='')
        self.busy = True
        self.request_id = str(uuid.uuid4())
        self.send_button.state(['disabled'])
        self.stop_button.state(['!disabled'])
        self._set_status('generating', 'Генерирую ответ…')
        self.render('')
        kwargs = dict(conversation_id=self.conversation, model=self.model_var.get() or None, web=self.web_var.get(),
                      attachments=attachments, regenerate=regenerate, edit_message_id=edit_id, request_id=self.request_id)

        def job():
            try:
                for event in self.client.chat_stream(text, **kwargs):
                    self.events.put(('stream', event))
            except Unauthorized:
                self.events.put(('unauthorized', None))
            except (HostError, AuthError, OSError) as exc:
                self.events.put(('stream', {'type': 'error', 'message': str(exc)}))
            finally:
                self.events.put(('stream-end', None))
        self._background(job)

    def stop(self):
        if self.busy and self.request_id:
            self._api(self.client.stop, self.request_id, then=None)
            self._set_status('ready', 'Останавливаю…')

    def regenerate(self):
        if self.conversation and self.messages:
            self.send(regenerate=True, text='')

    def edit_last(self):
        last = next((m for m in reversed(self.messages) if m['role'] == 'user' and m.get('id')), None)
        if not last or self.busy:
            return
        from tkinter import simpledialog
        text = simpledialog.askstring('Изменить сообщение', 'Новый текст сообщения:', initialvalue=last['content'],
                                      parent=self.root)
        if text and text.strip():
            self.send(edit_id=last['id'], text=text.strip())

    def copy_answer(self):
        last = next((m for m in reversed(self.messages) if m['role'] == 'assistant'), None)
        if last:
            self.root.clipboard_clear()
            self.root.clipboard_append(last['content'])
            self._set_status('ready', 'Ответ скопирован')

    def sync(self):
        if self.client:
            self._set_status('syncing', 'Синхронизация…')
            self._api(self.client.sync, then='synced')

    def mind_window(self):
        win=Toplevel(self.root)
        win.title('Chelsy Mind · документы')
        prompt=Text(win,height=4,width=70)
        prompt.pack(fill='x',padx=12,pady=8)
        status=StringVar(value='Опишите задачу и нужный формат.')
        ttk.Label(win,textvariable=status,wraplength=480).pack(fill='x',padx=12)
        listing=Listbox(win)
        listing.pack(fill='both',expand=True,padx=12,pady=8)
        entries=[]
        pending={}
        client=self.client
        def run(fn,done):
            events=queue.Queue()
            def work():
                try: events.put((True,fn()))
                except Exception as exc: events.put((False,str(exc)))
            def poll():
                if not win.winfo_exists(): return
                try: ok,value=events.get_nowait()
                except queue.Empty:
                    win.after(100,poll)
                    return
                if ok: done(value)
                else: status.set(value)
            threading.Thread(target=work,daemon=True).start()
            win.after(100,poll)
        def listed(result):
            entries[:]=result['artifacts']
            listing.delete(0,END)
            for art in entries: listing.insert(END,art['filename'])
        def refresh(): run(lambda:client.call('GET','/api/v3/artifacts'),listed)
        def submit():
            text=prompt.get('1.0',END).strip()
            if not text: return
            token=pending.setdefault(text,str(uuid.uuid4()))
            status.set('Host обрабатывает задачу…')
            def done(result):
                pending.pop(text,None)
                status.set(result['answer'] or result['meta']['status'])
                refresh()
            run(lambda:client.call('POST','/api/v3/mind/run',{'message':text,'idempotency_key':token}),done)
        def save():
            if not listing.curselection(): return
            art=entries[listing.curselection()[0]]
            dest=filedialog.asksaveasfilename(parent=win,initialfile=art['filename'])
            if not dest: return
            def write():
                import hashlib,tempfile
                with client._open('GET','/api/v3/artifacts/'+art['id']+'/download') as response:
                    raw=response.read(25*1024*1024+1)
                if hashlib.sha256(raw).hexdigest()!=art['sha256']: raise ValueError('Ошибка проверки файла.')
                with tempfile.NamedTemporaryFile(dir=Path(dest).parent,delete=False) as tmp:
                    try:
                        tmp.write(raw)
                        tmp.close()
                        os.replace(tmp.name,dest)
                    finally: Path(tmp.name).unlink(missing_ok=True)
                return 'Файл сохранён.'
            run(write,status.set)
        for label,fn in [('Отправить',submit),('Обновить список',refresh),('Скачать выбранный файл',save)]:
            ttk.Button(win,text=label,command=fn).pack(side='left',padx=6,pady=6)
        refresh()

    def logout(self):
        try:
            if self._account():
                client_cache.clear(self._account())   # shared PCs: no chat copies after sign-out
        except (OSError, ValueError):
            pass
        self.session.logout()
        self.client = None
        if self.main_frame:
            self.main_frame.destroy()
            self.main_frame = None
        self.login_frame = self._login_view()

    # ------------------------------------------------------------------ research & knowledge windows
    def open_research(self):
        if not self.client:
            return
        win = Toplevel(self.root, bg=BG)
        win.title('Исследования — Chelsy AI')
        top = ttk.Frame(win, padding=10)
        top.pack(fill='x')
        topic = StringVar()
        ttk.Label(top, text='Тема или ссылка:').pack(side='left')
        ttk.Entry(top, textvariable=topic, width=60).pack(side='left', padx=6, ipady=3)
        info = ttk.Label(win, text='Найденные материалы попадут в базу знаний только после твоего решения.', style='Muted.TLabel')
        info.pack(anchor='w', padx=10)
        jobs = ttk.Treeview(win, columns=('topic', 'status', 'progress', 'message'), show='headings', height=6)
        for col, title, width in (('topic', 'Тема', 260), ('status', 'Статус', 90), ('progress', '%', 50), ('message', 'Сообщение', 480)):
            jobs.heading(col, text=title)
            jobs.column(col, width=width)
        jobs.pack(fill='x', padx=10, pady=6)
        items = ttk.Treeview(win, columns=('status', 'trust', 'date', 'title', 'url'), show='headings', selectmode='extended')
        for col, title, width in (('status', 'Статус', 90), ('trust', 'Доверие', 60), ('date', 'Дата', 90), ('title', 'Заголовок', 330), ('url', 'Ссылка', 330)):
            items.heading(col, text=title)
            items.column(col, width=width)
        # The action row is packed at the bottom before the list expands, so it is never clipped.
        actions = ttk.Frame(win, padding=10)
        actions.pack(side='bottom', fill='x')
        items.pack(fill='both', expand=True, padx=10)

        def refresh_jobs():
            def job():
                try:
                    data = self.client.research()
                    self.events.put(('call', (lambda d=data: fill_jobs(d), None)))
                except (HostError, AuthError, OSError) as exc:
                    self.events.put(('error', str(exc)))
            self._background(job)

        def fill_jobs(data):
            jobs.delete(*jobs.get_children())
            for j in data:
                jobs.insert('', END, iid=j['id'], values=(j['topic'][:60], RESEARCH_STATUS.get(j['status'], j['status']),
                                                          int(j['progress'] * 100), j['message'][:100]))

        def show_items(_=None):
            sel = jobs.selection()
            if not sel:
                return

            def job():
                try:
                    data = self.client.research_job(sel[0])
                    self.events.put(('call', (lambda d=data: fill_items(d), None)))
                except (HostError, AuthError, OSError) as exc:
                    self.events.put(('error', str(exc)))
            self._background(job)

        def fill_items(data):
            items.delete(*items.get_children())
            for i in data['items']:
                items.insert('', END, iid=str(i['id']), values=(RESEARCH_STATUS.get(i['status'], i['status']), f'{i["trust"]:.2f}', (i['published'] or '—')[:10], i['title'][:80], i['url']))

        def review(action, scope='personal'):
            selected = items.selection()

            def job():
                for item_id in selected:
                    try:
                        self.client.review_item(int(item_id), action, scope)
                    except HostError as exc:
                        self.events.put(('error', str(exc)))
                self.events.put(('call', (show_items, None)))
            self._background(job)

        def start():
            if len(topic.get().strip()) < 3:
                return
            self._api(self.client.start_research, topic.get().strip(), then=None)
            win.after(800, refresh_jobs)

        def stop_job():
            sel = jobs.selection()
            if sel:
                self._api(self.client.stop_research, sel[0], then=None)
                win.after(800, refresh_jobs)
        ttk.Button(top, text='Начать', style='Accent.TButton', command=start).pack(side='left')
        ttk.Button(top, text='Остановить', command=stop_job).pack(side='left', padx=4)
        ttk.Button(top, text='Обновить', style='Flat.TButton', command=refresh_jobs).pack(side='left')
        ttk.Button(actions, text='В личную базу', style='Accent.TButton', command=lambda: review('accept')).pack(side='left')
        ttk.Button(actions, text='В общую базу (владелец)', command=lambda: review('accept', 'shared')).pack(side='left', padx=6)
        ttk.Button(actions, text='Отклонить', command=lambda: review('reject')).pack(side='left')
        ttk.Button(actions, text='Открыть ссылку', command=lambda: [webbrowser.open(items.item(i)['values'][4]) for i in items.selection()[:1]
                                                                    if str(items.item(i)['values'][4]).startswith('https://')]).pack(side='right')
        jobs.bind('<<TreeviewSelect>>', show_items)
        # Size from what the widgets ask for, so no button row is cut off at any DPI.
        win.update_idletasks()
        need_w = max(980, top.winfo_reqwidth() + 20, actions.winfo_reqwidth() + 20)
        need_h = max(640, win.winfo_reqheight())
        win.geometry(f'{need_w}x{need_h}')
        win.minsize(min(need_w, actions.winfo_reqwidth() + 20), top.winfo_reqheight() + actions.winfo_reqheight() + 260)

        def tick():
            if win.winfo_exists():
                refresh_jobs()
                win.after(5000, tick)
        tick()

    def open_knowledge(self):
        if not self.client:
            return
        win = Toplevel(self.root, bg=BG)
        win.title('База знаний — Chelsy AI')
        win.geometry('900x560')
        summary = ttk.Label(win, text='Загрузка…', padding=10)
        summary.pack(anchor='w')
        tree = ttk.Treeview(win, columns=('scope', 'title', 'date', 'trust', 'url'), show='headings')
        for col, title, width in (('scope', 'База', 70), ('title', 'Заголовок', 330), ('date', 'Опубликовано', 100), ('trust', 'Доверие', 60), ('url', 'Ссылка', 320)):
            tree.heading(col, text=title)
            tree.column(col, width=width)
        tree.pack(fill='both', expand=True, padx=10, pady=10)
        ttk.Label(win, text='Журнал автоизучения — что Chelsy изучила сама', style='Muted.TLabel').pack(anchor='w', padx=10)
        journal = Text(win, height=9, wrap='word', bg=PANEL, fg=TEXT, borderwidth=0, font=('Segoe UI', 9))
        journal.pack(fill='x', padx=10, pady=(2, 10))
        labels = {'learned': 'изучено', 'added': 'добавлено', 'auto-job': 'начато', 'auto-done': 'готово',
                  'skipped': 'на проверку', 'limit': 'лимит', 'error': 'ошибка'}

        def fill_journal(data):
            journal.delete('1.0', END)
            for e in data.get('journal', []):
                journal.insert(END, f'{e["created"][:16].replace("T", " ")}  {labels.get(e["event"], e["event"])}  '
                                    f'{e["title"][:90]}  {e["detail"][:80]}\n')
            if not data.get('journal'):
                journal.insert(END, 'Пока пусто. Chelsy начнёт изучать источники после ответов с поиском в интернете.')

        def load_journal():
            try:
                data = self.client.learning()
                self.events.put(('call', (lambda d=data: fill_journal(d), None)))
            except (HostError, AuthError, OSError):
                pass
        self._background(load_journal)

        def fill(data):
            st = data['stats']
            summary.configure(text=f'Документов: {st["documents"]} · фрагментов: {st["chunks"]} · возможных противоречий: {st["open_conflicts"]}')
            for d in data['documents']:
                tree.insert('', END, values=('личная' if d['personal'] else 'общая', d['title'][:70], (d['published'] or '—')[:10], f'{d["trust"]:.2f}', d['url']))

        def job():
            try:
                data = self.client.knowledge()
                self.events.put(('call', (lambda d=data: fill(d), None)))
            except (HostError, AuthError, OSError) as exc:
                self.events.put(('error', str(exc)))
        self._background(job)

    # ------------------------------------------------------------------ event loop
    def _poll(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle(kind, payload)
        except queue.Empty:
            pass
        self.root.after(50, self._poll)

    def _handle(self, kind, payload):
        if kind == 'logged-in':
            self._remember(host=payload, email=self.session.email or self.email_var.get())
            self.client = HostClient(payload, self.session.token)
            self.login_frame.destroy()
            self.main_frame = self._main_view()
            self.render()
            self._api(self.client.status, then='status')
            self.load_conversations()
        elif kind == 'login-error':
            self.login_button.state(['!disabled'])
            self.login_status.configure(text=payload)
        elif kind == 'unauthorized':
            messagebox.showwarning('Chelsy AI', 'Сессия истекла. Войди снова.')
            self.logout()
        elif kind == 'offline':
            if self.main_frame:
                self._set_status('offline', payload)
        elif kind == 'error':
            if self.main_frame:
                self._set_status('offline', payload[:90])
            else:
                messagebox.showerror('Chelsy AI', payload)
        elif kind == 'call':
            then, result = payload
            if callable(then):
                then()
            elif then == 'conversations':
                self._show_conversations(result)
            elif then == 'messages':
                self.messages = result
                self.render()
            elif then == 'refresh':
                self.load_conversations()
            elif then == 'status':
                models = result.get('models') or []
                self.model_box.configure(values=models)
                if models and not self.model_var.get():
                    self.model_var.set(result.get('default_model') if result.get('default_model') in models else models[0])
                ok = result.get('ollama')
                self._set_status('ready' if ok else 'offline',
                                 f'Host {result.get("version", "")} · ' + ('модель готова' if ok else 'Ollama недоступна на хосте'))
            elif then == 'synced':
                self._set_status('ready', f'Синхронизировано · получено {result.get("received", 0)}')
                self.load_conversations()
        elif kind == 'stream':
            self._stream_event(payload)
        elif kind == 'stream-end':
            self.busy = False
            self.send_button.state(['!disabled'])
            self.stop_button.state(['disabled'])
            if self.conversation:
                self._api(self._cached_messages, self.conversation, then='messages')
            self.load_conversations()

    def _stream_event(self, event):
        etype = event.get('type')
        if etype == 'start':
            self.conversation = event.get('conversation_id') or self.conversation
            self._streaming = ''
        elif etype == 'status':
            self._set_status(event.get('state', 'generating'), event.get('text', ''))
            if not getattr(self, '_streaming', ''):
                self.render('_' + event.get('text', '') + '_')
        elif etype == 'delta':
            self._streaming = getattr(self, '_streaming', '') + event.get('text', '')
            self.render(self._streaming)
        elif etype in ('replace', 'done'):
            self._streaming = event.get('text', '')
            if etype == 'done':
                self.messages.append({'role': 'assistant', 'content': self._streaming, 'id': event.get('message_id')})
                self.render()
                self._set_status('ready', 'Готова к работе')
            else:
                self.render(self._streaming)
        elif etype == 'error':
            self._set_status('offline', event.get('message', 'Ошибка'))
            self.messages.append({'role': 'assistant', 'content': '⚠️ ' + event.get('message', 'Ошибка соединения с хостом')})
            self.render()

    def run(self):
        self.root.mainloop()
