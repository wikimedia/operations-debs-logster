from logster.parsers.JsonLogster import JsonLogster
from logster.logster_helper import MetricObject
import unittest

class TestJsonLogster(unittest.TestCase):
    def setUp(self):
        self.json_line = '{     "1.1": {         "value1": 0,         "value2": "hi",         "1.2": {             "value3": 0.1,             "value4": false         }     },     "2.1": ["a","b"] }'
        self.json_data = {
            '1.1': {
                'value1': 0,
                'value2': 'hi',
                '1.2': {
                    'value3': 0.1,
                    'value4': False,
                }
            },
            '2.1': ['a','b'],
            '2.1': ['a','b'],
            # '/' should be replaced with key_separator
            '3/1': 'nonya',
        }
        self.key_separator = '&'
        self.flattened_should_be = {
            '1.1&value1': 0,
            '1.1&valuetwo': 'hi',
            '1.1&1.2&value3': 0.1,
            '1.1&1.2&value4': False,
            '2.1&0': 'a',
            '2.1&1': 'b',
            # '/' should be replaced with key_separator
            '3&1': 'nonya',
        }

        self.json_logster = JsonLogster('--key-separator ' + self.key_separator)

    def key_filter_callback(self, key):
        if key == 'value2':
            key = 'valuetwo'

        return key

    def test_init(self):
        self.assertEquals(self.json_logster.key_separator, self.key_separator)

    def test_flatten_object(self):
        flattened = self.json_logster.flatten_object(self.json_data, self.key_separator, self.key_filter_callback)
        self.assertEquals(flattened, self.flattened_should_be)

    def test_infer_metric_type(self):
        self.assertEquals('float', self.json_logster.infer_metric_type(1.2))
        self.assertEquals('int32', self.json_logster.infer_metric_type(1))
        self.assertEquals('string', self.json_logster.infer_metric_type('woohooo'))
        self.assertEquals('string', self.json_logster.infer_metric_type(False))

    def test_get_metric_object(self):
        should_be = MetricObject('int', 1, type='int32')
        metric_object = self.json_logster.get_metric_object('int', 1)
        self.assertEquals(should_be.name, metric_object.name)
        self.assertEquals(should_be.value, metric_object.value)
        self.assertEquals(should_be.type, metric_object.type)

        should_be = MetricObject('bool', 'False', type='string')
        metric_object = self.json_logster.get_metric_object('bool', False)
        self.assertEquals(should_be.name, metric_object.name)
        self.assertEquals(should_be.value, metric_object.value)
        self.assertEquals(should_be.type, metric_object.type)

if __name__ == '__main__':
    unittest.main()