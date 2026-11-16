"""Windows Client GUI smoke test. Runs where Tk is available (e.g. the Windows CI runner);
skipped on headless Linux without tkinter. No network: the host client is a stub."""
import os
import tempfile
import unittest

try:
    import tkinter
    tkinter.Tk().destroy()
    TK = True
except Exception:          # no tkinter module or no display
    TK = False


@unittest.skipUnless(TK, 'Tk is not available in this environment')
class ClientGuiSmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = self.tmp.name

    def tearDown(self):
        import supabase_auth
        supabase_auth.allow_bundled_config(False)   # the GUI enables it process-wide; do not leak into other tests
        if self.old is None:
            os.environ.pop('LOCALAPPDATA', None)
        else:
            os.environ['LOCALAPPDATA'] = self.old
        self.tmp.cleanup()

    def test_build_login_and_main_views(self):
        import client_gui
        app = client_gui.ChelsyClientApp()
        try:
            self.assertEqual(app.root.title(), 'Chelsy AI · Client 0.9.3')
            app.session.email = 'tester@example.org'
            app.login_frame.destroy()
            app.main_frame = app._main_view()
            app.messages = [{'role': 'user', 'content': 'Почему небо голубое?'},
                            {'role': 'assistant', 'content': '# Ответ\nДело в **рассеянии**.\n```python\nprint(1)\n```\n[Источник](https://example.org)'}]
            app.render()
            text = app.chat.get('1.0', 'end')
            self.assertIn('рассеянии', text)
            self.assertIn('print(1)', text)
            self.assertNotIn('**', text)
            app._show_conversations([{'id': 'a', 'title': 'Чат', 'favorite': True, 'updated': '2'},
                                     {'id': 'b', 'title': 'Другой', 'favorite': False, 'updated': '1'}])
            # Groups instead of glyph markers: header, favourite, header, recent.
            self.assertEqual([app.conv_list.get(i).strip() for i in range(4)], ['Избранное', 'Чат', 'Недавние', 'Другой'])
            self.assertIsNone(app._row_conversation(0))
            self.assertEqual(app._row_conversation(1)['id'], 'a')
            app.messages = [{'role': 'assistant', 'content': 'Это *курсив*, _тоже курсив_ и дата 2026-11-12.'}]
            app.render()
            self.assertNotIn('*', app.chat.get('1.0', 'end'))
            self.assertTrue(app.chat.tag_ranges('italic'))
            self.assertTrue(app.chat.tag_ranges('date'))
            for state in ('generating', 'searching', 'syncing', 'offline', 'ready'):
                app._set_status(state, state)
                app.root.update()
            self.assertIsNone(app.aurora._job)          # still when Chelsy is idle
            app.root.update()
        finally:
            app.root.destroy()


if __name__ == '__main__':
    unittest.main()
