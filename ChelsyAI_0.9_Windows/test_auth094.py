"""0.9.4 own authentication: SEC-02, SEC-04, ADM-01/03, MIG-01. Real SQLite, real Argon2id/bcrypt/AES-GCM."""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt

import migrations
from auth import passwords, vault
from auth.service import AuthError, AuthService
from auth.throttle import Throttle

PW = 'Северное сияние над тайгой 2026'
PW2 = 'Комета пролетела над маяком ночью'


class Clock:
    def __init__(self):
        self.now = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, **kw):
        self.now += timedelta(**kw)


class FakeMonotonic:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class AuthTests(unittest.TestCase):
    def setUp(self):
        passwords.configure({'time_cost': 2, 'memory_cost': 19456, 'parallelism': 1})
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'chelsy.db'
        migrations.migrate(self.db)
        self.clock = Clock()
        self.mono = FakeMonotonic()
        self.auth = AuthService(self.db, throttle=Throttle(clock=self.mono), clock=self.clock)
        self.auth.save_profile(argon2={'time_cost': 2, 'memory_cost': 19456, 'parallelism': 1})

    def tearDown(self):
        self.tmp.cleanup()

    def user(self, email='alice@example.org', password=PW):
        uid, temp = self.auth.create_account('test', email, 'Алиса')
        first = self.auth.login(email, temp)
        self.assertEqual(first['status'], 'password_change_required')
        done = self.auth.complete_password_change(first['change_token'], password)
        self.assertEqual(done['status'], 'ok')
        self.assertIn('recovery_code', done)
        return uid, done

    @staticmethod
    def admin_pw(n):
        return PW + (' первый страж' if n == 1 else ' второй страж')

    def admins(self):
        created = self.auth.setup_admins_local('admin1@chelsy.group', 'admin2@chelsy.group')
        sessions = []
        for n, (email, temp) in enumerate(created, 1):
            first = self.auth.login(email, temp)
            sessions.append(self.auth.complete_password_change(first['change_token'], self.admin_pw(n)))
        return [self.auth.authenticate(s['access_token']) for s in sessions]

    # ---------------------------------------------------------------- sign-in
    def test_first_login_requires_own_password_and_issues_recovery_code(self):
        uid, done = self.user()
        p = self.auth.authenticate(done['access_token'])
        self.assertEqual((p.account_id, p.role), (uid, 'user'))
        self.assertIsNotNone(p.dek)
        again = self.auth.login('ALICE@example.org', PW)
        self.assertEqual(again['status'], 'ok')
        self.assertNotIn('recovery_code', again)

    def test_wrong_password_and_unknown_email_give_the_same_error(self):
        self.user()
        errors = []
        for email in ('alice@example.org', 'nobody@example.org', 'not-an-email'):
            with self.assertRaises(AuthError) as ctx:
                self.auth.login(email, 'неверный пароль для проверки')
            errors.append((ctx.exception.status, ctx.exception.message))
        self.assertEqual(len(set(errors)), 1)

    def test_bruteforce_is_slowed_but_never_locks_the_owner_out_forever(self):
        self.user()
        for _ in range(5):
            with self.assertRaises(AuthError):
                self.auth.login('alice@example.org', 'неверный пароль для проверки', ip='203.0.113.9')
        with self.assertRaises(AuthError) as ctx:
            self.auth.login('alice@example.org', PW, ip='203.0.113.9')
        self.assertEqual(ctx.exception.code, 'throttled')
        # the real owner on another network is not affected
        self.assertEqual(self.auth.login('alice@example.org', PW, ip='198.51.100.7')['status'], 'ok')
        # and the attacker's wait is temporary
        self.mono.t += 16 * 60
        self.assertEqual(self.auth.login('alice@example.org', PW, ip='203.0.113.9')['status'], 'ok')

    def test_password_policy(self):
        uid, temp = self.auth.create_account('test', 'bob@example.org')
        first = self.auth.login('bob@example.org', temp)
        with self.assertRaises(passwords.PasswordPolicyError):
            self.auth.complete_password_change(first['change_token'], 'короткий')
        first = self.auth.login('bob@example.org', temp)
        with self.assertRaises(passwords.PasswordPolicyError):
            self.auth.complete_password_change(first['change_token'], '123456789012345')
        self.assertEqual(len(PW * 2), 62)
        first = self.auth.login('bob@example.org', temp)
        self.assertEqual(self.auth.complete_password_change(first['change_token'], (PW + ' ' + PW2)[:64])['status'], 'ok')

    # ---------------------------------------------------------------- sessions
    def test_access_expires_after_ten_minutes_and_refresh_rotates(self):
        _, s = self.user()
        self.clock.advance(minutes=11)
        with self.assertRaises(AuthError) as ctx:
            self.auth.authenticate(s['access_token'])
        self.assertEqual(ctx.exception.code, 'access_expired')
        new = self.auth.refresh(s['refresh_token'])
        p = self.auth.authenticate(new['access_token'])
        self.assertIsNotNone(p.dek)                       # the data key survives rotation via the token
        self.assertNotEqual(new['refresh_token'], s['refresh_token'])

    def test_reused_refresh_token_revokes_the_whole_family(self):
        _, s = self.user()
        new = self.auth.refresh(s['refresh_token'])
        with self.assertRaises(AuthError) as ctx:
            self.auth.refresh(s['refresh_token'])           # stolen copy of the old token
        self.assertEqual(ctx.exception.code, 'refresh_reuse')
        with self.assertRaises(AuthError):
            self.auth.authenticate(new['access_token'])     # the legitimate one is revoked too
        with self.assertRaises(AuthError):
            self.auth.refresh(new['refresh_token'])

    def test_logout_and_revoke_all_close_access_immediately(self):
        _, s1 = self.user()
        s2 = self.auth.login('alice@example.org', PW, device='телефон')
        p1 = self.auth.authenticate(s1['access_token'])
        self.assertEqual(len(self.auth.sessions_for(p1)), 2)
        self.auth.revoke_all(p1, keep_current=True)
        with self.assertRaises(AuthError):
            self.auth.authenticate(s2['access_token'])
        self.auth.logout(p1)
        with self.assertRaises(AuthError):
            self.auth.authenticate(s1['access_token'])

    def test_password_change_keeps_data_key_and_revokes_other_sessions(self):
        _, s1 = self.user()
        other = self.auth.login('alice@example.org', PW)
        p = self.auth.authenticate(s1['access_token'])
        secret = vault.encrypt_text(p.dek, 'личное', p.username, p.key_version)
        with self.assertRaises(AuthError):
            self.auth.change_password(p, 'не тот пароль совсем', PW2)
        changed = self.auth.change_password(p, PW, PW2)
        with self.assertRaises(AuthError):
            self.auth.authenticate(other['access_token'])
        p2 = self.auth.authenticate(changed['access_token'])
        self.assertEqual(vault.decrypt_text(p2.dek, secret, p2.username, p2.key_version), 'личное')
        relog = self.auth.authenticate(self.auth.login('alice@example.org', PW2)['access_token'])
        self.assertEqual(vault.decrypt_text(relog.dek, secret, relog.username, relog.key_version), 'личное')

    # ---------------------------------------------------------------- SEC-04
    def test_admin_password_reset_does_not_open_old_content(self):
        a1, _ = self.admins()
        uid, s = self.user()
        p = self.auth.authenticate(s['access_token'])
        code = s['recovery_code']
        secret = vault.encrypt_text(p.dek, 'тайна Алисы', p.username, p.key_version)
        temp = self.auth.admin_reset_password(a1, uid, 'пользователь забыл пароль')
        # the admin knows the one-time password, but signing in with it never yields the data key
        first = self.auth.login('alice@example.org', temp)
        self.assertEqual(first['status'], 'password_change_required')
        step = self.auth.complete_password_change(first['change_token'], PW2)
        self.assertEqual(step['status'], 'key_recovery_required')
        # with the user's recovery code the old content opens again
        opened = self.auth.authenticate(self.auth.recover_keys(step['recovery_token'], code.lower())['access_token'])
        self.assertEqual(vault.decrypt_text(opened.dek, secret, opened.username, opened.key_version), 'тайна Алисы')

    def test_without_recovery_code_old_content_stays_closed(self):
        a1, _ = self.admins()
        uid, s = self.user()
        p = self.auth.authenticate(s['access_token'])
        secret = vault.encrypt_text(p.dek, 'тайна', p.username, p.key_version)
        temp = self.auth.admin_reset_password(a1, uid, 'утрата')
        step = self.auth.complete_password_change(self.auth.login('alice@example.org', temp)['change_token'], PW2)
        with self.assertRaises(AuthError):
            self.auth.recover_keys(step['recovery_token'], 'AAAA-BBBB-CCCC-DDDD-EEEE-FFFF')
        fresh_token = self.auth.login('alice@example.org', PW2)['recovery_token']
        fresh = self.auth.recover_keys(fresh_token, None)
        self.assertIn('recovery_code', fresh)
        np = self.auth.authenticate(fresh['access_token'])
        self.assertEqual(np.key_version, 2)
        self.assertEqual(vault.decrypt_text(np.dek, secret, np.username, np.key_version), vault.LOCKED_TEXT)

    def test_admin_lists_only_service_fields(self):
        a1, _ = self.admins()
        self.user()
        rows = self.auth.admin_accounts(a1)
        self.assertTrue(rows)
        forbidden = {'pw_hash', 'avatar', 'settings', 'content', 'title'}
        for row in rows:
            self.assertFalse(forbidden & set(row), row.keys())

    def test_regular_user_cannot_use_admin_functions(self):
        self.admins()
        uid, s = self.user()
        p = self.auth.authenticate(s['access_token'])
        for call in (lambda: self.auth.admin_accounts(p), lambda: self.auth.admin_reset_password(p, uid, 'x'),
                     lambda: self.auth.request_joint_action(p, 'replace_admin', {'slot': 1, 'email': 'alice@example.org'}, 'x')):
            with self.assertRaises(AuthError) as ctx:
                call()
            self.assertEqual(ctx.exception.status, 403)
        # editing the profile cannot raise the role
        self.auth.update_profile(p, display_name='admin', settings={'role': 'admin'})
        self.assertEqual(self.auth.authenticate(s['access_token']).role, 'user')

    # ---------------------------------------------------------------- ADM-01
    def test_exactly_two_admins_and_joint_replacement(self):
        a1, a2 = self.admins()
        self.assertEqual([r['slot'] for r in self.auth.roster()], [1, 2])
        with self.assertRaises(AuthError):
            self.auth.setup_admins_local('x@chelsy.group', 'y@chelsy.group')       # no silent third/override
        uid, s = self.user('carol@example.org')
        rid = self.auth.request_joint_action(a1, 'replace_admin', {'slot': 2, 'email': 'carol@example.org'}, 'смена')
        with self.assertRaises(AuthError):
            self.auth.decide_joint_action(a1, rid, True)                              # same admin cannot confirm
        self.auth.decide_joint_action(a2, rid, True)
        emails = [r['email'] for r in self.auth.roster()]
        self.assertEqual(emails, ['admin1@chelsy.group', 'carol@example.org'])
        with self.assertRaises(AuthError):
            self.auth.authenticate(s['access_token'])                                 # role change revokes sessions
        with self.assertRaises(AuthError):
            self.auth.admin_accounts(self.auth.authenticate(self.auth.login('admin2@chelsy.group', self.admin_pw(2))['access_token']))

    def test_admin_cannot_block_the_other_admin_alone(self):
        a1, a2 = self.admins()
        with self.assertRaises(AuthError):
            self.auth.admin_set_blocked(a1, a2.account_id, True, 'конфликт')
        with self.assertRaises(AuthError):
            self.auth.admin_reset_password(a1, a2.account_id, 'захват')

    def test_admin_session_ends_after_fifteen_idle_minutes(self):
        a1, _ = self.admins()
        self.clock.advance(minutes=9)
        tokens = self.auth.refresh(self.auth.login('admin1@chelsy.group', self.admin_pw(1))['refresh_token'])
        self.clock.advance(minutes=16)
        with self.assertRaises(AuthError):
            self.auth.authenticate(tokens['access_token'])

    def test_audit_log_has_actor_reason_and_no_content(self):
        a1, _ = self.admins()
        uid, _ = self.user()
        self.auth.admin_set_blocked(a1, uid, True, 'спам')
        entry = self.auth.admin_audit_log(a1)[0]
        self.assertEqual((entry['actor'], entry['action'], entry['target'], entry['reason']), (a1.account_id, 'block', uid, 'спам'))
        with self.assertRaises(AuthError) as ctx:
            self.auth.login('alice@example.org', PW)
        self.assertEqual(ctx.exception.code, 'blocked')

    # ---------------------------------------------------------------- MIG-01
    def test_supabase_bcrypt_account_keeps_uuid_and_upgrades_to_argon2(self):
        old = bcrypt.hashpw(PW.encode(), bcrypt.gensalt(10)).decode().replace('$2b$', '$2a$')
        uid = 'f3a6c1de-1111-4222-8333-444455556666'
        self.assertTrue(self.auth.import_account(account_id=uid, email='Old@Example.org', pw_hash=old, display_name='Старый'))
        self.assertFalse(self.auth.import_account(account_id=uid, email='old@example.org', pw_hash=old))
        result = self.auth.login('old@example.org', PW)
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.auth.authenticate(result['access_token']).username, 'sb:' + uid)
        with sqlite3.connect(self.db) as c:
            self.assertTrue(c.execute('SELECT pw_hash FROM accounts WHERE id=?', (uid,)).fetchone()[0].startswith('$argon2id$'))

    def test_imported_short_password_must_be_changed(self):
        old = bcrypt.hashpw(b'short-old-1', bcrypt.gensalt(10)).decode()
        self.auth.import_account(account_id='aaaaaaaa-1111-4222-8333-444455556666', email='s@example.org', pw_hash=old)
        self.assertEqual(self.auth.login('s@example.org', 'short-old-1')['status'], 'password_change_required')


if __name__ == '__main__':
    unittest.main()
