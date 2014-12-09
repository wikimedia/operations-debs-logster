###  JsonLogster parses a file of JsonObjects, each on their own line.
###  The object will be traversed, and each leaf node of the object will
###  be keyed by a concatenated key made up of all parent keys.
###
###  For example:
###  sudo ./logster --dry-run --output=ganglia --parser-options '--key-separator _' JsonLogster /var/cache/stats.log.json
###
import json
import optparse

from logster.logster_helper import MetricObject, LogsterParser
from logster.logster_helper import LogsterParsingException

class JsonLogster(LogsterParser):
    '''
    JsonLogster parses a file of JsonObjects, each on their own line.
    The object will be traversed, and each leaf node of the object will
    be keyed by a concatenated key made up of all parent keys.
    You can subclass this class and implement the key_filter method
    to skip or transform specific keys in the object hierarchy.
    '''

    def __init__(self, option_string=None):
        '''Initialize any data structures or variables needed for keeping track
        of the tasty bits we find in the log we are parsing.'''
        self.metrics = {}

        if option_string:
            options = option_string.split(' ')
        else:
            options = []

        optparser = optparse.OptionParser()
        optparser.add_option('--key-separator', '-k', dest='key_separator', default='.',
        help='Key separator for flattened json object key name. Default: \'.\'  \'/\' and \':\' are not allowed.''')

        opts, args = optparser.parse_args(args=options)
        self.key_separator = opts.key_separator

        if self.key_separator == '/' or self.key_separator == ':':
            raise RuntimeError('Cannot use : or / as key_separator.')

    def key_filter(self, key):
        '''
        Default key_filter method.  Override and implement
        this method if you want to do any filtering or transforming
        on specific keys in your JSON object.  This translates
        key_separator and ':' to underscores.
        '''
        return key.replace(self.key_separator, '_').replace(':', '_')

    def get_metric_object(self, metric_name, metric_value):
        '''
        Default key_to_metric_object method.
        Given a metric name and value, this returns
        a MetricObject filled in.  This default method
        will attempt to infer MetricObject.type from the metric_value
        type, but nothing more.  If you need to set any particular
        MetricObject parameters (such as slope, title, etc.),
        you should override this method.
        '''
        metric_type = self.infer_metric_type(metric_value)
        # make sure the metric value is properly a string.
        if metric_type == 'string':
            metric_value = str(metric_value)

        return MetricObject(metric_name, metric_value, type=metric_type)

    def infer_metric_type(self, metric_value):
        '''
        Infers MetricObject type from the
        variable type of metric_value.
        '''
        if isinstance(metric_value, float):
            metric_type = 'float'
        # use int32 for int and long.
        # If bool, use 'string'. (bool is a subtype of int)
        elif (isinstance(metric_value, int) or isinstance(metric_value, long)) and not isinstance(metric_value, bool):
            metric_type = 'int32'
        else:
            metric_type = 'string'

        return metric_type

    def flatten_object(self, node, separator='.', key_filter_callback=None, parent_keys=[]):
        '''
        Recurses through dicts and/or lists and flattens them
        into a single level dict of key: value pairs.  Each
        key consists of all of the recursed keys joined by
        separator.  If key_filter_callback is callable,
        it will be called with each key.  It should return
        either a new key which will be used in the final full
        key string, or False, which will indicate that this
        key and its value should be skipped.
        '''
        flattened = {}

        try:
            iterator = node.iteritems()
        except AttributeError:
            iterator = enumerate(node)

        for key, child in iterator:
            # If key_filter_callback was provided,
            # then call it on the key.  If the returned
            # key is false, then, we know to skip it.
            if callable(key_filter_callback):
                key = key_filter_callback(key)
            if key is False:
                continue

            # append this key to the end of all keys seen so far
            all_keys = parent_keys + [str(key)]

            if hasattr(child, '__iter__'):
                # merge the child items all together
                flattened.update(self.flatten_object(child, separator, key_filter_callback, all_keys))
            else:
                # '/' is  not allowed in key names.
                # Ganglia writes files based on key names
                # and doesn't escape these in the path.
                final_key = separator.join(all_keys).replace('/', self.key_separator)
                flattened[final_key] = child

        return flattened

    def parse_line(self, line):
        '''This function should digest the contents of one line at a time, updating
        object's state variables. Takes a single argument, the line to be parsed.'''

        json_data = json.loads(line)
        # Using update() in order to work with multiple lines.
        # Since lines are parsed in order as they appear in the file,
        # if there are multiple entries for the same key, this will
        # end up using the latest value for that key.
        self.metrics.update(self.flatten_object(json.loads(line), self.key_separator, self.key_filter))

    def get_state(self, duration):
        '''Run any necessary calculations on the data collected from the logs
        and return a list of metric objects.'''
        self.duration = duration

        metric_objects = []
        for metric_name, metric_value in self.metrics.items():
            metric_objects.append(self.get_metric_object(metric_name, metric_value))

        return metric_objects

