"""Sanity checks for desktop navigation and UI construction."""
import unittest
import app

class TestDesktopUI(unittest.TestCase):
    def test_navigation_shows_only_target(self):
        values = app.navigate('Память')
        self.assertEqual([v['visible'] for v in values], [False, False, True, False, False])

    def test_ui_builds_without_runtime_server(self):
        ui = app.build()
        self.assertGreater(len(ui.blocks), 30)

class SourcesDisplay(unittest.TestCase):
    def test_source_dates_become_turquoise_spans_only_in_the_footer(self):
        text = 'В 2026-01-01 вышло.\n\n---\n**Источники из интернета:**\n1. [FastAPI](https://fastapi.tiangolo.com/) · 2026-11-12'
        shown = app.display_text(text)
        self.assertIn('· <span class="chelsy-date">2026-11-12</span>', shown)
        self.assertIn('В 2026-01-01 вышло.', shown)   # body dates untouched
        self.assertEqual(app.display_text(None), '')


if __name__ == '__main__':
    unittest.main()
