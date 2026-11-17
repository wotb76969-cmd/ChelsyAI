"""Tests for own Auth + Mind artifacts (0.9.4)."""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

os.environ['CHELSY_APPDATA'] = '1'
os.environ['CHELSY_AUTH_MODE'] = 'own'

import core
import migrations
from auth import (
    AuthError, authenticate_user, create_user, create_session, resolve_access_token,
    refresh_session, revoke_session, change_password, ensure_bootstrap_admins,
    list_users_admin, set_user_status, validate_password_policy, PasswordError,
)
from auth.rate_limit import reset_for_tests
from mind import MindEngine
from mind.router import TaskRouter
from mind.artifacts import build_artifact, validate_artifact
from mind.artifacts.builder import ArtifactSpec


class Auth094Test(unittest.TestCase):
    def setUp(self):
        reset_for_tests()
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 't.db'
        core.DB_PATH = self.db_path  # type: ignore
        core.DATA = Path(self.tmp.name)  # type: ignore
        migrations.migrate(self.db_path)
        self.conn = sqlite3.connect(self.db_path, timeout=15)

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def test_password_policy(self):
        with self.assertRaises(PasswordError):
            validate_password_policy('short')
        validate_password_policy('correct-horse-battery')

    def test_register_login_session(self):
        user = create_user(self.conn, 'user1@example.com', 'correct-horse-battery', display_name='U1')
        self.conn.commit()
        auth = authenticate_user(self.conn, 'user1@example.com', 'correct-horse-battery', source='1.2.3.4')
        self.assertEqual(auth['id'], user['id'])
        tokens = create_session(self.conn, user['id'])
        self.conn.commit()
        session = resolve_access_token(self.conn, tokens['access_token'])
        self.assertEqual(session['user_id'], user['id'])
        rotated = refresh_session(self.conn, tokens['refresh_token'])
        self.conn.commit()
        self.assertTrue(rotated['access_token'])
        # reuse old refresh → revoked
        with self.assertRaises(ValueError):
            refresh_session(self.conn, tokens['refresh_token'])

    def test_login_does_not_reveal_email(self):
        with self.assertRaises(AuthError):
            authenticate_user(self.conn, 'nosuch@example.com', 'correct-horse-battery', source='ip')
        create_user(self.conn, 'user2@example.com', 'correct-horse-battery')
        self.conn.commit()
        with self.assertRaises(AuthError) as ctx:
            authenticate_user(self.conn, 'user2@example.com', 'wrong-password-xxxx', source='ip')
        self.assertIn('Неверный', str(ctx.exception))

    def test_admin_cannot_be_self_assigned(self):
        u = create_user(self.conn, 'u@example.com', 'correct-horse-battery')
        self.conn.commit()
        # role stays user unless created as admin by bootstrap/admin API
        self.assertEqual(u['role'], 'user')

    def test_two_admins_cap(self):
        create_user(self.conn, 'a1@example.com', 'correct-horse-battery', role='admin')
        create_user(self.conn, 'a2@example.com', 'correct-horse-battery', role='admin')
        self.conn.commit()
        with self.assertRaises(AuthError):
            create_user(self.conn, 'a3@example.com', 'correct-horse-battery', role='admin')

    def test_change_password_revokes_wrap(self):
        u = create_user(self.conn, 'p@example.com', 'correct-horse-battery')
        self.conn.commit()
        change_password(self.conn, u['id'], 'correct-horse-battery', 'another-strong-pass1')
        self.conn.commit()
        authenticate_user(self.conn, 'p@example.com', 'another-strong-pass1', source='x')


class Mind094Test(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / 't.db'
        core.DB_PATH = self.db_path  # type: ignore
        core.DATA = Path(self.tmp.name)  # type: ignore
        migrations.migrate(self.db_path)
        self.conn = sqlite3.connect(self.db_path, timeout=15)
        self.user = create_user(self.conn, 'm@example.com', 'correct-horse-battery')
        self.conn.commit()
        self.engine = MindEngine(self.conn, Path(self.tmp.name) / 'artifacts')

    def tearDown(self):
        try:
            self.conn.close()
        except Exception:
            pass
        self.tmp.cleanup()

    def test_router_routes_docx(self):
        r = TaskRouter().route('Создай DOCX на три страницы про отпуск')
        self.assertEqual(r.route, 'docx')

    def test_build_all_formats(self):
        prompts = {
            'txt': 'Создай txt список дел на завтра',
            'docx': 'Создай DOCX на три страницы про проект',
            'pdf': 'Сделай PDF инструкцию по входу',
            'pptx': 'Сделай презентацию на восемь слайдов о запуске',
            'xlsx': 'Подготовь XLSX-бюджет с итогами',
        }
        for fmt, prompt in prompts.items():
            result = self.engine.handle(self.user['id'], prompt)
            self.assertEqual(result.route, fmt, result)
            self.assertTrue(result.artifact_id)
            art = self.engine.get_artifact(self.user['id'], result.artifact_id)
            self.assertTrue(Path(art['storage_path']).is_file())
            validate_artifact(fmt, Path(art['storage_path']))

    def test_idor_blocked(self):
        other = create_user(self.conn, 'other@example.com', 'correct-horse-battery')
        self.conn.commit()
        result = self.engine.handle(self.user['id'], 'Создай txt заметку')
        with self.assertRaises(PermissionError):
            self.engine.get_artifact(other['id'], result.artifact_id)

    def test_admin_list_has_no_content_fields(self):
        create_user(self.conn, 'adm@example.com', 'correct-horse-battery', role='admin')
        self.conn.commit()
        users = list_users_admin(self.conn)
        for u in users:
            self.assertNotIn('password_hash', u)
            self.assertNotIn('key_wrap_json', u)
            for forbidden in ('chat', 'message', 'memory', 'content'):
                self.assertTrue(all(forbidden not in k for k in u))


class Migration094Test(unittest.TestCase):
    def test_migrate_to_v6(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'm.db'
            applied = migrations.migrate(path)
            self.assertIn(5, applied)
            self.assertIn(6, applied)
            info = migrations.inspect(path)
            self.assertEqual(info['version'], 6)
            self.assertIn('auth_users', info['tables'])
            self.assertIn('mind_artifacts', info['tables'])


if __name__ == '__main__':
    unittest.main()
