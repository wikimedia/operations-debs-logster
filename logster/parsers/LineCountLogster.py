###  Simple line counter parser.  This returns the rate of matching line creation.
###
###  Examples:
###
###  # without --regex flag, match any lines.  This will just output the line creation rate.
###  sudo ./logster --dry-run --output=ganglia LineCountLogster /var/log/syslog

###  # with --regex flag, only report counts for lines that match --regex
###  sudo ./logster --dry-run --output=ganglia --parser-options '--regex=^ERROR ' LineCountLogster /var/log/mylog.log

import time
import re
import optparse

from logster.logster_helper import MetricObject, LogsterParser
from logster.logster_helper import LogsterParsingException

from pprint import pprint as pp

class LineCountLogster(LogsterParser):

    def __init__(self, option_string=None):
        '''Initialize any data structures or variables needed for keeping track
        of the tasty bits we find in the log we are parsing.'''
        self.line_count = 0

        optparser = optparse.OptionParser()
        optparser.add_option('--regex', '-r', dest='regex', default=None,
                            help='regex for which to match lines against')

        if option_string:
            options = option_string.split(' ')
        else:
            options = []
        opts, args = optparser.parse_args(args=options)

        if opts.regex:
            self.regex = re.compile(opts.regex)
        else:
            self.regex = None

    def parse_line(self, line):
        '''This function should digest the contents of one line at a time, updating
        object's state variables. Takes a single argument, the line to be parsed.'''

        if (self.regex == None or self.regex.match(line)):
            self.line_count += 1

    def get_state(self, duration):
        '''Run any necessary calculations on the data collected from the logs
        and return a list of metric objects.'''
        self.duration = duration

        # Return a list of metrics objects
        return [
            MetricObject('line_rate',  (float(self.line_count) / float(self.duration)), 'lines per sec', type='float'),
        ]

