"""Host administration: Supabase admin client, owner-only service, secret storage, plan limits.
No network: Supabase is a fake opener that records every request."""
import datetime as dt
import io
import json
import os
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import admin_service as svc

OWNER = '11111111-1111-4111-8111-111111111111'
ALICE = '22222222-2222-4222-8222-222222222222'
SECRET = 'sb_secret_' + 'x' * 32


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSupabase:
    """Records requests; answers the Auth Admin API and PostgREST like Supabase does."""

    def __init__(self):
        self.requests = []
        self.users = [
            {'id': OWNER, 'email': 'owner@chelsy.group', 'email_confirmed_at': '2026-10-01T10:00:00Z',
             'created_at': '2026-10-01T10:00:00Z', 'last_sign_in_at': '2026-11-16T09:00:00Z'},
            {'id': ALICE, 'email': 'alice@example.org', 'email_confirmed_at': None,
             'created_at': '2026-11-01T10:00:00Z', 'last_sign_in_at': '2026-11-15T09:00:00Z',
             'user_metadata': {'display_name': 'Алиса'}},
        ]
        self.subscriptions = []
        self.audit = []
        self.activity = []
        self.fail_tables = False

    def open(self, req, timeout=None):
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), req.full_url, dict(req.header_items()), body))
        url = req.full_url
        if self.fail_tables and '/rest/v1/chelsy_' in url:
            raise HTTPError(url, 404, 'nf', {}, io.BytesIO(b'{"code":"PGRST205"}'))
        if '/auth/v1/admin/users/' in url and req.get_method() == 'PUT':
            uid = url.rsplit('/', 1)[1]
            user = next(u for u in self.users if u['id'] == uid)
            if body.get('ban_duration') == svc.FOREVER_BAN:
                user['banned_until'] = '2126-01-01T00:00:00Z'
            elif body.get('ban_duration') == 'none':
                user.pop('banned_until', None)
            if body.get('email_confirm'):
                user['email_confirmed_at'] = '2026-11-16T12:00:00Z'
            return FakeResponse(json.dumps(user).encode())
        if '/auth/v1/admin/users/' in url:
            uid = url.rsplit('/', 1)[1].split('?')[0]
            return FakeResponse(json.dumps(next(u for u in self.users if u['id'] == uid)).encode())
        if '/auth/v1/admin/users' in url:
            return FakeResponse(json.dumps({'users': self.users}).encode())
        if '/auth/v1/recover' in url:
            return FakeResponse(b'{}')
        if '/rest/v1/profiles' in url:
            return FakeResponse(json.dumps([{'id': ALICE, 'display_name': 'Алиса', 'plan': 'pro'}]).encode())
        if '/rest/v1/chelsy_subscriptions' in url:
            if req.get_method() == 'POST':
                row = {'id': len(self.subscriptions) + 1, **body}
                self.subscriptions.append(row)
                return FakeResponse(json.dumps([row]).encode())
            if req.get_method() == 'PATCH':
                sid = int(url.split('id=eq.')[1].split('&')[0])
                hit = [r for r in self.subscriptions if r['id'] == sid and r['status'] == 'active']
                for r in hit:
                    r.update(body)
                return FakeResponse(json.dumps(hit).encode())
            rows = self.subscriptions
            if 'status=eq.active' in url:
                rows = [r for r in rows if r['status'] == 'active']
            return FakeResponse(json.dumps(rows).encode())
        if '/rest/v1/chelsy_admin_audit' in url:
            if req.get_method() == 'POST':
                self.audit.append(body)
                return FakeResponse(json.dumps([body]).encode())
            return FakeResponse(json.dumps(self.audit).encode())
        if '/rest/v1/chelsy_activity' in url:
            if req.get_method() == 'POST':
                self.activity.extend(body if isinstance(body, list) else [body])
                return FakeResponse(b'')
            return FakeResponse(json.dumps(self.activity).encode())
        raise AssertionError('unexpected request ' + url)


class AdminTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'LOCALAPPDATA': self.tmp.name, 'CHELSY_ADMIN_USER_ID': OWNER}, clear=False)
        self.env.start()
        os.environ.pop('CHELSY_SUPABASE_SECRET_KEY', None)
        self.fake = FakeSupabase()
        self.db = Path(self.tmp.name) / 'chelsy.db'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE messages (id INTEGER PRIMARY KEY, username TEXT, role TEXT, content TEXT, created TEXT)')
            today = dt.date.today().isoformat()
            conn.executemany('INSERT INTO messages(username,role,content,created) VALUES(?,?,?,?)', [
                ('sb:' + ALICE, 'user', 'секрет', today + 'T10:00:00'),
                ('sb:' + ALICE, 'assistant', 'ответ', today + 'T10:00:05'),
                ('sb:' + ALICE, 'user', 'ещё', '2026-01-01T10:00:00'),
            ])

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def client(self):
        return svc.SupabaseAdmin(url='https://demo.supabase.co', key=SECRET, opener=self.fake)

    def service(self, admin=OWNER):
        return svc.AdminService(admin, client=self.client(), db_path=self.db)

    # -- access
    def test_only_the_host_owner_gets_the_service(self):
        with self.assertRaises(svc.AdminError):
            self.service(ALICE)
        self.assertEqual(self.service().admin_id, OWNER)

    def test_secret_key_goes_only_in_the_apikey_header(self):
        self.client().list_users()
        method, url, headers, _ = self.fake.requests[0]
        self.assertTrue(url.startswith('https://demo.supabase.co/auth/v1/admin/users'))
        self.assertEqual(headers['Apikey'], SECRET)
        self.assertNotIn('Authorization', headers)

    def test_missing_tables_explain_the_migration(self):
        self.fake.fail_tables = True
        with self.assertRaises(svc.AdminError) as ctx:
            self.service().subscriptions()
        self.assertIn('004_admin_subscriptions_activity.sql', str(ctx.exception))

    # -- accounts
    def test_accounts_merge_auth_profiles_plans_and_local_usage(self):
        s = self.service()
        s.grant(ALICE, 'plus', 30, 'бета')
        rows = {r['id']: r for r in s.accounts()}
        alice = rows[ALICE]
        self.assertEqual(alice['plan'], 'plus')
        self.assertEqual(alice['wanted_plan'], 'pro')
        self.assertEqual(alice['name'], 'Алиса')
        self.assertEqual(alice['state'], 'не подтверждён')
        self.assertEqual((alice['messages'], alice['today']), (3, 1))
        self.assertTrue(rows[OWNER]['is_admin'])
        self.assertEqual([r['email'] for r in s.accounts('алис')], ['alice@example.org'])

    def test_grant_and_revoke_are_audited(self):
        s = self.service()
        row = s.grant(ALICE, 'pro', 90, 'подарок')
        self.assertEqual(row['granted_by'], OWNER)
        ends = dt.datetime.fromisoformat(row['ends_at'].replace('Z', '+00:00'))
        self.assertAlmostEqual((ends - dt.datetime.now(dt.timezone.utc)).days, 89, delta=1)
        s.revoke(row['id'])
        self.assertEqual(self.fake.subscriptions[0]['status'], 'revoked')
        self.assertEqual([a['action'] for a in self.fake.audit], ['grant_subscription', 'revoke_subscription'])
        with self.assertRaises(svc.AdminError):
            s.revoke(row['id'])                      # already revoked
        with self.assertRaises(svc.AdminError):
            s.grant(ALICE, 'ultra', 30)
        with self.assertRaises(svc.AdminError):
            s.grant(ALICE, 'plus', 0)

    def test_block_unblock_never_deletes_and_owner_cannot_lock_out(self):
        s = self.service()
        s.set_blocked(ALICE, True, 'спам')
        self.assertEqual(next(r for r in s.accounts() if r['id'] == ALICE)['state'], 'заблокирован')
        s.set_blocked(ALICE, False)
        self.assertNotIn('DELETE', [m for m, *_ in self.fake.requests])
        with self.assertRaises(svc.AdminError):
            s.set_blocked(OWNER, True)

    def test_confirm_email_and_password_reset(self):
        s = self.service()
        s.confirm_email(ALICE)
        self.assertEqual(s.send_password_reset(ALICE), 'alice@example.org')
        self.assertIn('send_password_reset', [a['action'] for a in self.fake.audit])

    def test_active_plan_picks_highest_current(self):
        now = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
        rows = [{'plan': 'team', 'status': 'revoked', 'starts_at': '2026-11-01T00:00:00Z'},
                {'plan': 'pro', 'status': 'active', 'starts_at': '2026-10-01T00:00:00Z', 'ends_at': '2026-11-10T00:00:00Z'},
                {'plan': 'plus', 'status': 'active', 'starts_at': '2026-11-01T00:00:00Z', 'ends_at': None}]
        self.assertEqual(svc.active_plan(rows, now)[0], 'plus')
        self.assertEqual(svc.active_plan([], now)[0], 'start')

    # -- secret storage
    def test_secret_key_storage_rejects_public_keys(self):
        with self.assertRaises(svc.AdminError):
            svc.save_secret_key('sb_publishable_abcdefghijklmnopqrstuvwxyz')
        with self.assertRaises(svc.AdminError):
            svc.save_secret_key('hello')
        self.assertIsNone(svc.secret_key())
        svc.save_secret_key(SECRET)
        self.assertEqual(svc.secret_key(), SECRET)
        stored = json.loads((Path(self.tmp.name) / 'ChelsyAI' / 'host_admin.json').read_text())
        if os.name != 'nt':
            self.assertEqual(oct((Path(self.tmp.name) / 'ChelsyAI' / 'host_admin.json').stat().st_mode & 0o777), '0o600')
        else:
            self.assertNotIn(SECRET, json.dumps(stored))    # DPAPI-encrypted on Windows
        svc.forget_secret_key()
        self.assertIsNone(svc.secret_key())

    def test_legacy_service_role_jwt_is_recognised(self):
        import base64
        payload = base64.urlsafe_b64encode(json.dumps({'role': 'service_role'}).encode()).decode().rstrip('=')
        self.assertTrue(svc.valid_secret_key('eyJhbGciOiJIUzI1NiJ9.' + payload + '.sig'))
        anon = base64.urlsafe_b64encode(json.dumps({'role': 'anon'}).encode()).decode().rstrip('=')
        self.assertFalse(svc.valid_secret_key('eyJhbGciOiJIUzI1NiJ9.' + anon + '.sig'))

    # -- plan limits on the host
    def test_daily_limit_is_off_by_default_and_applies_when_enabled(self):
        self.assertIsNone(svc.daily_limit_message(ALICE, 'token', self.db))
        svc.save_limits({'enabled': True, 'start': 1, 'plus': 300, 'pro': 1000, 'team': 0})
        with patch.object(svc, 'plan_for_token', return_value='start'):
            message = svc.daily_limit_message(ALICE, 'token', self.db)
        self.assertIn('Дневной лимит тарифа Start', message)
        with patch.object(svc, 'plan_for_token', return_value='team'):
            self.assertIsNone(svc.daily_limit_message(ALICE, 'token', self.db))

    def test_activity_without_secret_key_is_a_silent_no_op(self):
        svc.record_activity(ALICE, 'chat', '10 симв.', 'android')
        svc.record_activity('not-a-uuid', 'chat')
        self.assertEqual(self.fake.requests, [])


class AdminAppTests(unittest.TestCase):
    def test_login_accepts_only_the_owner(self):
        import admin_app
        with patch.dict(os.environ, {'CHELSY_ADMIN_USER_ID': OWNER}):
            with patch('supabase_auth.login', return_value={'user': {'id': ALICE}}):
                self.assertFalse(admin_app.authenticate('alice@example.org', 'pw'))
            with patch('supabase_auth.login', return_value={'user': {'id': OWNER}}):
                self.assertTrue(admin_app.authenticate('Owner@Chelsy.group', 'pw'))
        self.assertEqual(admin_app._SESSIONS['owner@chelsy.group'], OWNER)

    def test_handlers_keep_the_request_parameter_for_gradio(self):
        import inspect
        import admin_app
        for fn in (admin_app.load_accounts, admin_app.grant, admin_app.block, admin_app.load_activity):
            self.assertIn('request', inspect.signature(fn).parameters, fn.__name__)

    def test_panel_builds_and_formats_rows(self):
        import admin_app
        self.assertIsNotNone(admin_app.build())
        row = {'id': ALICE, 'email': 'a@b.c', 'name': '', 'state': 'активен', 'plan': 'pro', 'plan_until': None,
               'wanted_plan': '', 'created': None, 'last_sign_in': None, 'messages': 2, 'today': 1, 'is_admin': False}
        self.assertIn('Pro бессрочно', admin_app.card_html(row))
        self.assertEqual(admin_app.accounts_table([row])[0][3], 'Pro')
        self.assertEqual(admin_app.subscription_status({'status': 'active', 'plan': 'plus',
                                                        'starts_at': '2020-01-01T00:00:00Z',
                                                        'ends_at': '2021-01-01T00:00:00Z'}), 'истекла')


if __name__ == '__main__':
    unittest.main()
