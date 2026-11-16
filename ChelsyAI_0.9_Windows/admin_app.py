"""Chelsy AI — host administration panel (separate window, this computer only).

Runs on 127.0.0.1 and accepts only the Supabase account configured as the host owner
(admin_user_id). Uses the project's secret key that stays on the host (see admin_service).
"""
from __future__ import annotations

import datetime as dt
import functools
import html
import socket
import threading
from pathlib import Path

import gradio as gr

import admin_service as svc
import supabase_auth
from app import CSS, asset_path, brand_header_html, launch_kwargs

ADMIN_PORT_RANGE = range(7870, 7880)
_SESSIONS: dict[str, str] = {}            # login email (lower) -> Supabase user id
_LOCK = threading.Lock()
_EMAILS: dict[str, str] = {}              # user id -> email (for the activity feed)

STATE_LABEL = {'активен': 'активен', 'заблокирован': 'заблокирован', 'не подтверждён': 'не подтверждён'}
TERMS = {'30 дней': 30, '90 дней': 90, '1 год': 365, 'Бессрочно': None}
KINDS = {'Все действия': '', 'Запросы к Челси': 'chat', 'Исследования': 'research', 'Синхронизация': 'sync'}
KIND_LABEL = {'chat': 'запрос', 'research': 'исследование', 'sync': 'синхронизация'}
ACTION_LABEL = {'grant_subscription': 'выдана подписка', 'revoke_subscription': 'подписка отозвана',
                'block_user': 'аккаунт заблокирован', 'unblock_user': 'аккаунт разблокирован',
                'confirm_email': 'email подтверждён', 'send_password_reset': 'отправлена ссылка сброса пароля',
                'save_limits': 'изменены лимиты тарифов'}

ADMIN_CSS = CSS + r'''
.chelsy-admin-card { background:var(--chelsy-panel); border:1px solid var(--chelsy-stroke); border-radius:16px; padding:14px 16px; }
.chelsy-admin-card dl { display:grid; grid-template-columns:max-content 1fr; gap:6px 16px; margin:0; font-size:14px; }
.chelsy-admin-card dt { color:var(--chelsy-muted); }
.chelsy-admin-card dd { margin:0; }
.chelsy-badge { display:inline-block; padding:1px 9px; border-radius:999px; font-size:12.5px; background:var(--chelsy-raised); }
.chelsy-badge.ok { color:var(--chelsy-teal); } .chelsy-badge.warn { color:var(--chelsy-danger); } .chelsy-badge.plan { color:var(--chelsy-lavender); }
.chelsy-admin-summary { display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 8px; }
.chelsy-admin-summary div { background:var(--chelsy-panel); border-radius:12px; padding:8px 14px; font-size:13px; color:var(--chelsy-muted); }
.chelsy-admin-summary b { display:block; font-size:20px; color:var(--chelsy-text); font-variant-numeric:tabular-nums; }
.chelsy-admin-table td:nth-child(n) { white-space:nowrap; }
'''


# ------------------------------------------------------------------ auth
def authenticate(email: str, password: str) -> bool:
    """Gradio login: Supabase password sign-in, then the owner check."""
    try:
        result = supabase_auth.login(email, password)
    except (supabase_auth.AuthError, ValueError):
        return False
    uid = (result.get('user') or {}).get('id', '')
    owner = supabase_auth.admin_user_id()
    if not owner or uid != owner:
        return False
    with _LOCK:
        _SESSIONS[email.strip().lower()] = uid
    return True


def service(request: gr.Request) -> svc.AdminService:
    with _LOCK:
        uid = _SESSIONS.get((request.username or '').strip().lower()) if request else None
    if not uid:
        raise gr.Error('Сессия администратора не найдена. Войди заново.')
    try:
        return svc.AdminService(uid)
    except svc.AdminError as exc:
        raise gr.Error(str(exc)) from exc


def guarded(fn):
    """Show AdminError as a readable notification instead of a stack trace.
    functools.wraps keeps the signature: Gradio injects gr.Request by the type hint."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except svc.AdminError as exc:
            raise gr.Error(str(exc)) from exc
    return wrapper


# ------------------------------------------------------------------ formatting
def _when(value) -> str:
    return svc._short(value) if value else '—'


def _plan(plan: str) -> str:
    return svc.PLANS.get(plan, plan or '—')


def accounts_table(rows):
    return [[r['email'], r['name'] or '—', r['state'], _plan(r['plan']),
             _when(r['plan_until']) if r['plan'] != 'start' else '—', _plan(r['wanted_plan']) if r['wanted_plan'] else '—',
             r['messages'], r['today'], _when(r['last_sign_in']), _when(r['created'])] for r in rows]


def summary_html(rows) -> str:
    total = len(rows)
    blocked = sum(r['state'] == 'заблокирован' for r in rows)
    paid = sum(r['plan'] != 'start' for r in rows)
    today = sum(1 for r in rows if r['today'])
    cells = [('Аккаунтов', total), ('С подпиской', paid), ('Активны сегодня', today), ('Заблокировано', blocked)]
    return '<div class="chelsy-admin-summary">' + ''.join(
        f'<div><b>{v}</b>{html.escape(k)}</div>' for k, v in cells) + '</div>'


def card_html(row: dict | None) -> str:
    if not row:
        return '<div class="chelsy-admin-card">Выбери аккаунт в списке.</div>'
    state_cls = 'ok' if row['state'] == 'активен' else 'warn'
    plan = _plan(row['plan']) + (f' до {_when(row["plan_until"])}' if row['plan'] != 'start' and row['plan_until'] else
                                 ' бессрочно' if row['plan'] != 'start' else '')
    items = [('Email', html.escape(row['email'])), ('Имя', html.escape(row['name'] or '—')),
             ('Состояние', f'<span class="chelsy-badge {state_cls}">{row["state"]}</span>'),
             ('Тариф', f'<span class="chelsy-badge plan">{html.escape(plan)}</span>'),
             ('Тариф при регистрации', html.escape(_plan(row['wanted_plan'])) if row['wanted_plan'] else '—'),
             ('Сообщений на хосте', f'<span class="num">{row["messages"]}</span> (сегодня <span class="num">{row["today"]}</span>)'),
             ('Последний вход', f'<span class="chelsy-date">{_when(row["last_sign_in"])}</span>'),
             ('Аккаунт создан', f'<span class="chelsy-date">{_when(row["created"])}</span>'),
             ('ID', f'<code>{row["id"]}</code>')]
    if row['is_admin']:
        items.insert(2, ('Роль', '<span class="chelsy-badge plan">администратор хоста</span>'))
    return '<div class="chelsy-admin-card"><dl>' + ''.join(f'<dt>{k}</dt><dd>{v}</dd>' for k, v in items) + '</dl></div>'


def subscription_status(row, now=None) -> str:
    if row.get('status') == 'revoked':
        return 'отозвана'
    plan, active = svc.active_plan([row], now)
    if active:
        return 'активна'
    starts = row.get('starts_at')
    if starts and dt.datetime.fromisoformat(str(starts).replace('Z', '+00:00')) > (now or svc._now()):
        return 'ещё не началась'
    return 'истекла'


def subscriptions_table(rows):
    return [[r['id'], _EMAILS.get(r['user_id'], r['user_id'][:8]), _plan(r['plan']), subscription_status(r),
             _when(r['starts_at']), _when(r['ends_at']) if r.get('ends_at') else 'бессрочно', r.get('note') or '']
            for r in rows]


def activity_table(rows):
    return [[_when(r['created_at']), _EMAILS.get(r['user_id'], r['user_id'][:8]), KIND_LABEL.get(r['kind'], r['kind']),
             r.get('detail') or '', r.get('device') or ''] for r in rows]


def audit_table(rows):
    return [[_when(r['created_at']), ACTION_LABEL.get(r['action'], r['action']),
             _EMAILS.get(r.get('target_id') or '', (r.get('target_id') or '—')[:8]),
             ', '.join(f'{k}: {v}' for k, v in (r.get('details') or {}).items() if v not in (None, ''))] for r in rows]


# ------------------------------------------------------------------ handlers
@guarded
def load_accounts(query, request: gr.Request):
    rows = service(request).accounts(query)
    with _LOCK:
        _EMAILS.update({r['id']: r['email'] for r in rows})
    choices = [(f'{r["email"]} · {_plan(r["plan"])} · {r["state"]}', r['id']) for r in rows]
    return accounts_table(rows), summary_html(rows), gr.update(choices=choices, value=None), rows


@guarded
def show_account(user_id, rows, request: gr.Request):
    row = next((r for r in rows or [] if r['id'] == user_id), None)
    if not row:
        return card_html(None), [], []
    s = service(request)
    return card_html(row), subscriptions_table(s.subscriptions(user_id)), activity_table(s.activity(user_id, limit=100))


@guarded
def grant(user_id, plan_label, term, note, query, request: gr.Request):
    if not user_id:
        raise gr.Error('Сначала выбери аккаунт.')
    plan = next(k for k, v in svc.PLANS.items() if v == plan_label)
    service(request).grant(user_id, plan, TERMS[term], note)
    gr.Info(f'Подписка {plan_label} выдана ({term.lower()}).')
    return load_accounts(query, request)


@guarded
def revoke(subscription_id, query, request: gr.Request):
    if not subscription_id:
        raise gr.Error('Укажи номер подписки из таблицы.')
    service(request).revoke(int(subscription_id))
    gr.Info(f'Подписка №{int(subscription_id)} отозвана.')
    return load_accounts(query, request)


@guarded
def block(user_id, confirmed, reason, query, request: gr.Request):
    if not user_id:
        raise gr.Error('Сначала выбери аккаунт.')
    if not confirmed:
        raise gr.Error('Отметь «Да, заблокировать этот аккаунт» — блокировка сразу закрывает вход на всех устройствах.')
    service(request).set_blocked(user_id, True, reason)
    gr.Info('Аккаунт заблокирован. Данные не удалены; разблокировать можно в любой момент.')
    return (*load_accounts(query, request), False)


@guarded
def unblock(user_id, query, request: gr.Request):
    if not user_id:
        raise gr.Error('Сначала выбери аккаунт.')
    service(request).set_blocked(user_id, False)
    gr.Info('Аккаунт разблокирован.')
    return load_accounts(query, request)


@guarded
def confirm_email(user_id, query, request: gr.Request):
    if not user_id:
        raise gr.Error('Сначала выбери аккаунт.')
    service(request).confirm_email(user_id)
    gr.Info('Email подтверждён вручную.')
    return load_accounts(query, request)


@guarded
def reset_password(user_id, request: gr.Request):
    if not user_id:
        raise gr.Error('Сначала выбери аккаунт.')
    email = service(request).send_password_reset(user_id)
    gr.Info(f'Ссылка для смены пароля отправлена на {email}.')


@guarded
def load_subscriptions(only_active, request: gr.Request):
    return subscriptions_table(service(request).subscriptions(only_active=only_active))


@guarded
def load_activity(kind_label, request: gr.Request):
    return activity_table(service(request).activity(kind=KINDS.get(kind_label, ''), limit=300))


@guarded
def load_audit(request: gr.Request):
    return audit_table(service(request).audit_log())


def key_status() -> str:
    key = svc.secret_key()
    if not key:
        return ('**Секретный ключ не задан.** Админ-панель и журнал действий не работают, пока ключ не сохранён. '
                'Где взять: Supabase → Project Settings → API Keys → **Secret keys** → создать/скопировать.')
    hidden = key[:14] + '…' + key[-4:]
    return f'Секретный ключ сохранён на этом компьютере: `{hidden}`. В клиенты и на сайт он не передаётся.'


@guarded
def save_key(key, request: gr.Request):
    service_check_owner(request)
    message = svc.save_secret_key(key)
    gr.Info(message)
    return key_status(), ''


def service_check_owner(request):
    with _LOCK:
        uid = _SESSIONS.get((request.username or '').strip().lower()) if request else None
    if not uid or uid != supabase_auth.admin_user_id():
        raise gr.Error('Доступ только для администратора хоста.')


@guarded
def check_connection(request: gr.Request):
    service_check_owner(request)
    gr.Info(svc.SupabaseAdmin().check())


@guarded
def forget_key(request: gr.Request):
    service_check_owner(request)
    svc.forget_secret_key()
    gr.Info('Секретный ключ удалён с этого компьютера.')
    return key_status()


@guarded
def save_limits(enabled, start, plus, pro, team, request: gr.Request):
    s = service(request)
    limits = svc.save_limits({'enabled': enabled, 'start': start, 'plus': plus, 'pro': pro, 'team': team})
    s._audit('save_limits', None, **{k: v for k, v in limits.items()})
    gr.Info('Лимиты сохранены. Хост применит их к следующим запросам.' if enabled else 'Лимиты сохранены (выключены).')


# ------------------------------------------------------------------ UI
def build():
    limits = svc.load_limits()
    migration = Path(__file__).resolve().parent / 'supabase' / '004_admin_subscriptions_activity.sql'
    with gr.Blocks(title='Chelsy AI — администрирование', fill_height=True) as demo:
        rows_state = gr.State([])
        with gr.Row(elem_id='chelsy-topbar'):
            gr.HTML(brand_header_html().replace('Desktop 0.9.3', 'Администрирование хоста'), scale=3)
        with gr.Tabs():
            with gr.Tab('Аккаунты'):
                summary = gr.HTML()
                with gr.Row():
                    query = gr.Textbox(placeholder='Email, имя или ID', show_label=False, scale=4)
                    refresh = gr.Button('Обновить', scale=1, min_width=120)
                table = gr.Dataframe(headers=['Email', 'Имя', 'Состояние', 'Тариф', 'До', 'Заявка',
                                              'Всего', 'Сегодня', 'Вход', 'Создан'],
                                     interactive=False, wrap=True, elem_classes='chelsy-admin-table',
                                     column_widths=['19%', '9%', '11%', '7%', '11%', '7%', '6%', '7%', '11%', '11%'])
                pick = gr.Dropdown(label='Аккаунт', choices=[], interactive=True)
                with gr.Row():
                    with gr.Column(scale=3):
                        card = gr.HTML(card_html(None))
                    with gr.Column(scale=2):
                        gr.Markdown('**Подписка**')
                        plan = gr.Dropdown(list(svc.PLANS.values())[1:], value='Plus', label='Тариф')
                        term = gr.Radio(list(TERMS), value='30 дней', label='Срок')
                        note = gr.Textbox(label='Комментарий (необязательно)', placeholder='Например: бета-тестер')
                        grant_btn = gr.Button('Выдать подписку', variant='primary')
                with gr.Row():
                    confirm_btn = gr.Button('Подтвердить email')
                    reset_btn = gr.Button('Отправить ссылку для смены пароля')
                    unblock_btn = gr.Button('Разблокировать')
                with gr.Accordion('Заблокировать аккаунт', open=False):
                    gr.Markdown('Блокировка запрещает вход на сайте, в Desktop, Windows Client и Android. '
                                'Аккаунт и его данные **не удаляются**.')
                    reason = gr.Textbox(label='Причина (для журнала)')
                    sure = gr.Checkbox(label='Да, заблокировать этот аккаунт')
                    block_btn = gr.Button('Заблокировать', variant='stop')
                gr.Markdown('**Подписки аккаунта**')
                user_subs = gr.Dataframe(headers=['№', 'Аккаунт', 'Тариф', 'Статус', 'С', 'До', 'Комментарий'],
                                         interactive=False, elem_classes='chelsy-admin-table')
                with gr.Row():
                    revoke_id = gr.Number(label='№ подписки', precision=0, scale=2)
                    revoke_btn = gr.Button('Отозвать подписку', scale=1)
                gr.Markdown('**Действия аккаунта** — только служебные данные (тип, размер, устройство), без текста сообщений.')
                user_activity = gr.Dataframe(headers=['Когда', 'Аккаунт', 'Действие', 'Детали', 'Устройство'],
                                             interactive=False, elem_classes='chelsy-admin-table')
            with gr.Tab('Подписки'):
                only_active = gr.Checkbox(label='Только активные', value=True)
                subs_refresh = gr.Button('Обновить', size='sm')
                subs_table = gr.Dataframe(headers=['№', 'Аккаунт', 'Тариф', 'Статус', 'С', 'До', 'Комментарий'],
                                          interactive=False, elem_classes='chelsy-admin-table')
            with gr.Tab('Активность'):
                with gr.Row():
                    kind = gr.Dropdown(list(KINDS), value='Все действия', label='Действие', scale=3)
                    act_refresh = gr.Button('Обновить', scale=1)
                act_table = gr.Dataframe(headers=['Когда', 'Аккаунт', 'Действие', 'Детали', 'Устройство'],
                                         interactive=False, elem_classes='chelsy-admin-table')
            with gr.Tab('Журнал администратора'):
                audit_refresh = gr.Button('Обновить', size='sm')
                audit = gr.Dataframe(headers=['Когда', 'Действие', 'Аккаунт', 'Подробности'], interactive=False,
                                     elem_classes='chelsy-admin-table')
            with gr.Tab('Настройки'):
                status = gr.Markdown(key_status())
                with gr.Row():
                    key = gr.Textbox(label='Секретный ключ Supabase', type='password', placeholder='sb_secret_…', scale=4)
                    save_key_btn = gr.Button('Сохранить ключ', variant='primary', scale=1)
                with gr.Row():
                    check_btn = gr.Button('Проверить подключение')
                    forget_btn = gr.Button('Удалить ключ с компьютера')
                gr.Markdown('### Лимиты запросов в день\nПрименяются хостом, если включены. 0 — без ограничений.')
                enabled = gr.Checkbox(label='Применять лимиты', value=limits['enabled'])
                with gr.Row():
                    lim = {p: gr.Number(label=svc.PLANS[p], value=limits[p], precision=0, minimum=0) for p in svc.PLAN_ORDER}
                save_limits_btn = gr.Button('Сохранить лимиты')
                with gr.Accordion('SQL-миграция для Supabase (один раз)', open=False):
                    gr.Markdown('Supabase → **SQL Editor** → вставь и выполни. Миграция только добавляет таблицы, '
                                'существующие данные и пользователи не меняются.')
                    gr.Code(migration.read_text(encoding='utf-8') if migration.exists() else '', language='sql')

        account_outputs = [table, summary, pick, rows_state]
        refresh.click(load_accounts, [query], account_outputs)
        query.submit(load_accounts, [query], account_outputs)
        demo.load(load_accounts, [query], account_outputs)
        pick.change(show_account, [pick, rows_state], [card, user_subs, user_activity])
        grant_btn.click(grant, [pick, plan, term, note, query], account_outputs).then(
            show_account, [pick, rows_state], [card, user_subs, user_activity])
        revoke_btn.click(revoke, [revoke_id, query], account_outputs).then(
            show_account, [pick, rows_state], [card, user_subs, user_activity])
        block_btn.click(block, [pick, sure, reason, query], account_outputs + [sure]).then(
            show_account, [pick, rows_state], [card, user_subs, user_activity])
        unblock_btn.click(unblock, [pick, query], account_outputs).then(
            show_account, [pick, rows_state], [card, user_subs, user_activity])
        confirm_btn.click(confirm_email, [pick, query], account_outputs).then(
            show_account, [pick, rows_state], [card, user_subs, user_activity])
        reset_btn.click(reset_password, [pick], None)
        subs_refresh.click(load_subscriptions, [only_active], [subs_table])
        only_active.change(load_subscriptions, [only_active], [subs_table])
        act_refresh.click(load_activity, [kind], [act_table])
        kind.change(load_activity, [kind], [act_table])
        audit_refresh.click(load_audit, None, [audit])
        save_key_btn.click(save_key, [key], [status, key])
        check_btn.click(check_connection, None, None)
        forget_btn.click(forget_key, None, [status])
        save_limits_btn.click(save_limits, [enabled, *lim.values()], None)
    return demo


def free_port() -> int:
    for port in ADMIN_PORT_RANGE:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return port
            except OSError:
                continue
    raise OSError('Нет свободного порта 7870–7879 для админ-панели.')


def main():
    supabase_auth.allow_bundled_config(True)
    if not supabase_auth.admin_user_id():
        raise SystemExit('Администратор хоста не задан. Запусти «Chelsy AI — настройка Supabase» и укажи admin_user_id.')
    kwargs = launch_kwargs()
    kwargs['css'] = ADMIN_CSS
    demo = build()
    demo.queue(default_concurrency_limit=2, api_open=False)
    demo.launch(server_name='127.0.0.1', server_port=free_port(), share=False, auth=authenticate,
                auth_message='Chelsy AI — администрирование. Вход только для владельца хоста.',
                inbrowser=True, show_error=False, enable_monitoring=False,
                favicon_path=str(asset_path('chelsy.ico')), **kwargs)


if __name__ == '__main__':
    main()
