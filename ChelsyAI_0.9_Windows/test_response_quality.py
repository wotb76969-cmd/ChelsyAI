import unittest
from unittest.mock import patch
import response_quality as rq


class ResponseQualityTests(unittest.TestCase):
    def test_screenshot_question(self):
        answer = rq.capability_answer('ты самостоятельно изучаешь интернет?', False)
        self.assertIn('не переобучаю', answer)
        self.assertIn('поиск в интернете недоступен', answer)
        self.assertNotIn('Brave', answer)      # no paid service is required any more
        self.assertNotIn('learn from', answer)

    def test_web_enabled(self):
        answer = rq.capability_answer('Ты обучаешься на данных сайтов?', True)
        self.assertIn('ищу актуальную информацию', answer)
        self.assertIn('без платных сервисов', answer)

    def test_unrelated_not_intercepted(self):
        self.assertIsNone(rq.capability_answer('Как изучать Python самостоятельно?'))

    def test_mixed_language(self):
        self.assertTrue(rq.is_mixed_russian_answer('Расскажи о себе',
            'Я не_selfstudy, я обучен на базе данных и learn from sources.'))
        self.assertFalse(rq.is_mixed_russian_answer('Напиши пример на Python',
            'Для Python можно использовать API и JSON. Код: `print("hello world")`.'))
        self.assertFalse(rq.is_mixed_russian_answer('Explain this', 'I learn from sources.'))

    def test_core_stores_honest_answer_without_ollama(self):
        import core
        with patch.object(core, 'save_message') as save, \
                patch.object(core, 'history', return_value=[{'role': 'assistant', 'content': 'ok'}]), \
                patch.object(core, 'extract_explicit_memory', return_value=None), \
                patch.dict('os.environ', {}, clear=True):
            chat, cleared = core.answer('Ты самостоятельно изучаешь интернет?', 'tester')
        self.assertEqual(cleared, '')
        self.assertEqual(save.call_count, 2)
        self.assertIn('не переобучаю', save.call_args.args[2])


class MixedLanguageTests(unittest.TestCase):
    Q = 'Почему небо голубое?'

    def test_english_prose_inside_russian_is_flagged(self):
        for answer in ('Дело в рассеянии света. This happens because shorter waves scatter more.',
                       'Это очень important момент и обычно relevant.',
                       'However, свет рассеивается сильнее.'):
            self.assertTrue(rq.is_mixed_russian_answer(self.Q, answer), answer)

    def test_product_names_code_and_source_titles_are_fine(self):
        for answer in ('Используй FastAPI и Pydantic, а запускай через Docker.',
                       'Источник: [FastAPI release notes](https://fastapi.tiangolo.com/) — свежая версия.',
                       'Это `print(name)` в Python.',
                       'Модель Llama Guard и библиотека Hugging Face Transformers.'):
            self.assertFalse(rq.is_mixed_russian_answer(self.Q, answer), answer)


if __name__ == '__main__':
    unittest.main()
