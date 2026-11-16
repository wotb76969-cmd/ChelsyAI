import unittest
from unittest.mock import patch
import live_tools

class LiveTests(unittest.TestCase):
    def test_intent(self):
        self.assertEqual(live_tools.search_intent('Какая погода в Москве?'),'weather')
        self.assertEqual(live_tools.search_intent('Последние новости Python'),'web')
        self.assertIsNone(live_tools.search_intent('Объясни переменные Python'))
    def test_greeting(self):
        self.assertIn('Привет',live_tools.chat_greeting('Привет!'))
        self.assertIn('порядке',live_tools.chat_greeting('Как дела?'))
    def test_weather_without_location(self):
        result, sources = live_tools.weather('Какая погода?')
        self.assertIn('город',result)
        self.assertEqual(sources,[])
    def test_weather_with_mocked_data(self):
        geo={'results':[{'name':'Москва','country':'Россия','latitude':55.75,'longitude':37.62}]}
        forecast={'current':{'temperature_2m':6,'apparent_temperature':3,'relative_humidity_2m':65,'wind_speed_10m':8,'weather_code':2,'time':'2026-11-11T12:00'}}
        with patch.object(live_tools,'fetch_json',side_effect=[geo,forecast]) as fetch:
            answer, sources = live_tools.weather('Какая погода в Москве сегодня?')
        self.assertIn('6 °C',answer)
        self.assertEqual(len(sources),1)
        self.assertEqual(fetch.call_count,2)
    def test_no_key_message(self):
        with patch.dict('os.environ',{},clear=True):
            results, note=live_tools.brave_search('новости')
        self.assertEqual(results,[])
        self.assertIn('CHELSY_BRAVE_SEARCH_KEY',note)
    def test_brave_result_mocked(self):
        with patch.dict('os.environ',{'CHELSY_BRAVE_SEARCH_KEY':'unit-test'}):
            with patch.object(live_tools,'fetch_json',return_value={'web':{'results':[{'url':'https://example.org/a','title':'Test','description':'Current info'}]}}):
                results,note=live_tools.brave_search('news')
        self.assertEqual(results[0]['title'],'Test')
        self.assertEqual(note,'')


class WeatherPlaceTests(unittest.TestCase):
    def test_places_from_russian_questions(self):
        cases = {
            'Какая погода в Самаре?': ('Самаре', None),
            'погода в Россия, Самара': ('Самара', 'RU'),
            'Погода: Самара, Россия': ('Самара', 'RU'),
            'погода Самара': ('Самара', None),
            'погода в Сочи завтра': ('Сочи', None),
            'weather in Samara today': ('Samara', None),
            'погода в моем городе': (None, None),
        }
        for question, expected in cases.items():
            self.assertEqual(live_tools.weather_place(question), expected, question)

    def test_nominative_candidates(self):
        self.assertIn('Самара', live_tools.place_candidates('Самаре'))
        self.assertIn('Казань', live_tools.place_candidates('Казани'))
        self.assertIn('Нижний Новгород', live_tools.place_candidates('Нижнем Новгороде'))
        self.assertIn('Ростов-на-Дону', live_tools.place_candidates('Ростове-на-Дону'))
        self.assertIn('Набережные Челны', live_tools.place_candidates('Набережных Челнах'))

    def _fake_geocoder(self, calls):
        cities = {'самара': {'name': 'Самара', 'country': 'Россия', 'admin1': 'Самарская область',
                             'latitude': 53.2, 'longitude': 50.15, 'population': 1163399}}
        forecast = {'current': {'temperature_2m': -3, 'apparent_temperature': -8, 'relative_humidity_2m': 80,
                                'wind_speed_10m': 12, 'weather_code': 71, 'time': '2026-11-16T12:00'}}

        def fetch(base, params, headers=None):
            calls.append(dict(params))
            if 'geocoding' in base:
                hit = cities.get(params['name'].casefold())
                return {'results': [hit]} if hit else {}
            return forecast
        return fetch

    def test_weather_in_samara_uses_nominative_form(self):
        calls = []
        with patch.object(live_tools, 'fetch_json', side_effect=self._fake_geocoder(calls)):
            answer, sources = live_tools.weather('Какая погода в Самаре?')
        self.assertIn('Самара', answer)
        self.assertIn('-3 °C', answer)
        self.assertEqual([c['name'] for c in calls if 'name' in c], ['Самаре', 'Самара'])

    def test_weather_country_and_city(self):
        calls = []
        with patch.object(live_tools, 'fetch_json', side_effect=self._fake_geocoder(calls)):
            answer, _ = live_tools.weather('погода в Россия, Самара')
        self.assertIn('Самара, Самарская область, Россия', answer)
        self.assertEqual(calls[0].get('countryCode'), 'RU')

    def test_followup_after_clarification(self):
        self.assertTrue(live_tools.is_weather_followup('Не нашла город «Самаре». Напиши…', 'Россия, Самара'))
        self.assertTrue(live_tools.is_weather_followup('Уточни город, пожалуйста.', 'Самара'))
        self.assertFalse(live_tools.is_weather_followup('Привет!', 'Россия, Самара'))
        self.assertFalse(live_tools.is_weather_followup('Уточни город, пожалуйста.', 'а почему небо голубое?'))


if __name__=='__main__': unittest.main()
