###  A sample logster parser file that can be used to count the number
###  of responses and object size in the squid access.log
###
###  For example:
###  sudo ./logster --dry-run --output=ganglia SquidLogster /var/log/squid/access.log
###
###
###  Copyright 2011, Etsy, Inc.
###
###  This file is part of Logster.
###
###  Logster is free software: you can redistribute it and/or modify
###  it under the terms of the GNU General Public License as published by
###  the Free Software Foundation, either version 3 of the License, or
###  (at your option) any later version.
###
###  Logster is distributed in the hope that it will be useful,
###  but WITHOUT ANY WARRANTY; without even the implied warranty of
###  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
###  GNU General Public License for more details.
###
###  You should have received a copy of the GNU General Public License
###  along with Logster. If not, see <http://www.gnu.org/licenses/>.
###

import re

from logster.logster_helper import MetricObject, LogsterParser
from logster.logster_helper import LogsterParsingException


class TopLevelUrlLogster(LogsterParser):

    def __init__(self, option_string=None):
        '''Initialize any data structures or variables needed for keeping track
        of the tasty bits we find in the log we are parsing.'''
        self.topurlstats = {}
        # Regular expression for matching lines we are interested in, and capturing
        # fields from the line (in this case, http_status_code, size and squid_code).
        self.reg = re.compile(r"""
        ^(?P<ip>(\d{1,3}\.?){4})
        \s-\s-\s
        \[(?P<timestamp>.*)\]\s
        "(?P<method>\w+)\s
        /(?P<toplevelurl>[^/]+)(?P<url>/.*?)"\s
        (?P<status>\d{3})\s
        (?P<len>\d+)\s
        "(?P<referer>.*?)"\s
        "(?P<useragent>.*?)"
        """, re.X)

    def parse_line(self, line):
        '''This function should digest the contents of one line at a time, updating
        object's state variables. Takes a single argument, the line to be parsed.'''

        # Apply regular expression to each line and extract interesting bits.
        regMatch = self.reg.match(line)

        if regMatch:
            bits = regMatch.groupdict()
            toplevel = bits['toplevelurl']
            status = bits['status']
            if toplevel in self.topurlstats:
                self.topurlstats[toplevel][status] = self.topurlstats[toplevel].get(status, 0) + 1
            else:
                self.topurlstats[toplevel] = {status: 1}
        else:
            raise LogsterParsingException("regmatch failed to match")

    def get_state(self, duration):
        '''Run any necessary calculations on the data collected from the logs
        and return a list of metric objects.'''

        metrics = []
        for topurl, statuses in self.topurlstats.items():
            for status, count in statuses.items():
                metric_name = 'raw.{topurl}.{status}'.format(topurl=topurl, status=status)
                metrics.append(MetricObject(metric_name, count, 'Responses'))
            metrics.append(MetricObject(
                'raw.{topurl}.all'.format(topurl=topurl),
                sum(statuses.values())
            ))

        return metrics
