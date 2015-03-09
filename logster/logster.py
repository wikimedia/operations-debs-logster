#!/usr/bin/python -tt
# -*- coding: utf-8 -*-

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
###  Forked from the ganglia-logtailer project
###  (http://bitbucket.org/maplebed/ganglia-logtailer):
###    Copyright Linden Research, Inc. 2008
###    Released under the GPL v2 or later.
###    For a full description of the license, please visit
###    http://www.gnu.org/licenses/gpl.txt
###

import os
import sys
import re
import optparse
import stat
import logging.handlers
import fcntl
import socket
import traceback

from time import time, strftime, gmtime
from math import floor

# Local dependencies
from logster_helper import LogsterParsingException, LockingError, CloudWatch, CloudWatchException

# Globals
gmetric = "/usr/bin/gmetric"
logtail = "/usr/sbin/logtail2"
log_dir = "/var/log/logster"
state_dir = "/var/run"
send_nsca = "/usr/sbin/send_nsca"

script_start_time = time()

# Logging infrastructure for use throughout the script.
# Uses appending log file, rotated at 100 MB, keeping 5.
if (not os.path.isdir(log_dir)):
    os.mkdir(log_dir)
logger = logging.getLogger('logster')
formatter = logging.Formatter('%(asctime)s %(levelname)-8s %(message)s')
hdlr = logging.handlers.RotatingFileHandler('%s/logster.log' % log_dir, 'a', 100 * 1024 * 1024, 5)
hdlr.setFormatter(formatter)
logger.addHandler(hdlr)
logger.setLevel(logging.INFO)


def get_cmdline_optparse():
    # Command-line options and parsing.
    cmdline = optparse.OptionParser(usage="usage: %prog [options] parser logfile",
        description="Tail a log file and filter each line to generate metrics that can be sent to common monitoring packages.")
    cmdline.add_option('--logtail', action='store', default=logtail,
                        help='Specify location of logtail.  Default %s' % logtail)
    cmdline.add_option('--metric-prefix', '-p', action='store',
                        help='Add prefix to all published metrics. This is for people that may multiple instances of same service on same host.',
                        default='')
    cmdline.add_option('--metric-suffix', '-x', action='store',
                        help='Add suffix to all published metrics. This is for people that may add suffix at the end of their metrics.',
                        default=None)
    cmdline.add_option('--parser-help', action='store_true',
                        help='Print usage and options for the selected parser')
    cmdline.add_option('--parser-options', action='store',
                        help='Options to pass to the logster parser such as "-o VALUE --option2 VALUE". These are parser-specific and passed directly to the parser.')
    cmdline.add_option('--gmetric-options', action='store',
                        help='Options to pass to gmetric such as "-d 180 -c /etc/ganglia/gmond.conf" (default). These are passed directly to gmetric.',
                        default='-d 180 -c /etc/ganglia/gmond.conf')
    cmdline.add_option('--graphite-host', action='store',
                        help='Hostname and port for Graphite collector, e.g. graphite.example.com:2003')
    cmdline.add_option('--statsd-host', action='store',
                        help='Hostname and port for statsd collector, e.g. statsd.example.com:8125')
    cmdline.add_option('--aws-key', action='store', default=os.getenv('AWS_ACCESS_KEY_ID'),
                        help='Amazon credential key')
    cmdline.add_option('--aws-secret-key', action='store', default=os.getenv('AWS_SECRET_ACCESS_KEY_ID'),
                        help='Amazon credential secret key')
    cmdline.add_option('--nsca-host', action='store',
                        help='Hostname and port for NSCA daemon, e.g. nsca.example.com:5667')
    cmdline.add_option('--nsca-service-hostname', action='store',
                        help='<host_name> value to use in nsca passive service check. Default is \"%default\"',
                        default=socket.gethostname())
    cmdline.add_option('--state-dir', '-s', action='store', default=state_dir,
                        help='Where to store the logtail state file.  Default location %s' % state_dir)
    cmdline.add_option('--log-dir', '-l', action='store', default=log_dir,
                        help='Where to store the logster logfile.  Default location %s' % log_dir)
    cmdline.add_option('--output', '-o', action='append',
                       choices=('graphite', 'ganglia', 'stdout', 'cloudwatch', 'nsca', 'statsd'),
                       help="Where to send metrics (can specify multiple times). Choices are 'graphite', 'ganglia', 'cloudwatch', 'nsca' , 'statsd', or 'stdout'.")
    cmdline.add_option('--stdout-separator', action='store', default="_", dest="stdout_separator",
                        help='Seperator between prefix/suffix and name for stdout. Default is \"%default\".')
    cmdline.add_option('--dry-run', '-d', action='store_true', default=False,
                        help='Parse the log file but send stats to standard output.')
    cmdline.add_option('--debug', '-D', action='store_true', default=False,
                        help='Provide more verbose logging for debugging.')
    return cmdline

## This provides a lineno() function to make it easy to grab the line
## number that we're on (for logging)
## Danny Yoo (dyoo@hkn.eecs.berkeley.edu)
## taken from http://aspn.activestate.com/ASPN/Cookbook/Python/Recipe/145297
import inspect
def lineno():
    """Returns the current line number in our program."""
    return inspect.currentframe().f_back.f_lineno


def is_number(s):
    """Return True if is a numeric string or type, False otherwise."""
    try:
        float(s)
        return True
    except ValueError:
        return False
    pass


def submit_stats(parser, duration, options):
    metrics = parser.get_state(duration)

    if 'ganglia' in options.output:
        submit_ganglia(metrics, options)
    if 'graphite' in options.output:
        submit_graphite(metrics, options)
    if 'stdout' in options.output:
        submit_stdout(metrics, options)
    if 'cloudwatch' in options.output:
        submit_cloudwatch(metrics, options)
    if 'nsca' in options.output:
        submit_nsca(metrics, options)
    if 'statsd' in options.output:
        submit_statsd(metrics, options)


def submit_stdout(metrics, options):
    for metric in metrics:
        metric_name = metric.name

        if (options.metric_prefix != ""):
            metric_name = options.metric_prefix + options.stdout_separator + metric_name
        if (options.metric_suffix is not None):
            metric_name = metric_name + options.stdout_separator + options.metric_suffix
        print "%s %s %s" %(metric.timestamp, metric_name, metric.value)

def submit_ganglia(metrics, options):
    for metric in metrics:
        metric_name = metric.name

        if (options.metric_prefix != ""):
            metric_name = options.metric_prefix + "_" + metric_name
        if (options.metric_suffix is not None):
            metric_name = metric_name + "_" + options.metric_suffix

        gmetric_cmd = "%s %s --name %s --value %s --type %s --units \"%s\" --title \"%s\" --desc  \"%s\" --slope \"%s\"" % (
            gmetric,
            options.gmetric_options,
            metric_name,
            metric.value,
            metric.type,
            metric.units,
            metric.title,
            metric.desc,
            metric.slope
        )
        logger.debug("Submitting Ganglia metric: %s" % gmetric_cmd)

        if (not options.dry_run):
            os.system("%s" % gmetric_cmd)
        else:
            print "%s" % gmetric_cmd


def submit_graphite(metrics, options):
    if (re.match("^[\w\.\-]+\:\d+$", options.graphite_host) == None):
        raise Exception, "Invalid host:port found for Graphite: '%s'" % options.graphite_host

    if (not options.dry_run):
        host = options.graphite_host.split(':')
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((host[0], int(host[1])))

    try:
        for metric in metrics:
            metric_name = metric.name

            if (options.metric_prefix != ""):
                metric_name = options.metric_prefix + "." + metric_name
            if (options.metric_suffix is not None):
                metric_name = metric_name + "." + options.metric_suffix

            metric_string = "%s %s %s" % (metric_name, metric.value, metric.timestamp)
            logger.debug("Submitting Graphite metric: %s" % metric_string)

            if (not options.dry_run):
                s.sendall("%s\n" % metric_string)
            else:
                print "%s %s" % (options.graphite_host, metric_string)
    finally:
        if (not options.dry_run):
            s.close()

def submit_cloudwatch(metrics, options):
    for metric in metrics:
        metric_name = metric.name

        if (options.metric_prefix != ""):
            metric_name = options.metric_prefix + "." + metric_name
        if (options.metric_suffix is not None):
            metric_name = metric_name + "." + options.metric_suffix

        metric.timestamp = strftime("%Y%m%dT%H:%M:00Z", gmtime(metric.timestamp))
        metric.units = "None"
        metric_string = "%s %s %s" % (metric_name, metric.value, metric.timestamp)
        logger.debug("Submitting CloudWatch metric: %s" % metric_string)

        if (not options.dry_run):
            try:
                cw = CloudWatch(options.aws_key, options.aws_secret_key, metric).get_instance_id()
            except CloudWatchException:
                logger.debug("Is this machine really amazon EC2?")
                sys.exit(1)

            try:
                cw.put_data()
            except CloudWatchException, e:
                logger.debug(e.message)
                sys.exit(1)
        else:
            print metric_string


def submit_nsca(metrics, options):
    if (re.match("^[\w\.\-]+\:\d+$", options.nsca_host) is None):
        raise Exception, "Invalid host:port found for NSCA: '%s'" % options.nsca_host

    host = options.nsca_host.split(':')

    for metric in metrics:
        metric_name = metric.name

        if (options.metric_prefix != ""):
            metric_name = options.metric_prefix + "_" + metric_name
        if (options.metric_suffix is not None):
            metric_name = metric_name + "_" + options.metric_suffix

        metric_string = "\t".join((options.nsca_service_hostname, metric_name, str(metric.value), metric.units,))
        logger.debug("Submitting NSCA status: %s" % metric_string)

        nsca_cmd = "echo '%s' | %s -H %s -p %s" % (metric_string, send_nsca, host[0], host[1],)

        if (not options.dry_run):
            os.system(nsca_cmd)
        else:
            print "%s" % nsca_cmd


def submit_statsd(metrics, options):
    if (not options.dry_run):
        host = options.statsd_host.split(':')

    for metric in metrics:
        metric_name = metric.name

        if (not is_number(metric.value)):
            print("WARNING: Cannot send %s to statsd, %s is not a numeric value." % (metric_name, metric.value))
            continue

        if (options.metric_prefix != ""):
            metric_name = options.metric_prefix + '.' + metric_name
        if (options.metric_suffix is not None):
            metric_name = metric_name + '.' + options.metric_suffix
        metric_string = "%s:%s|g" % (metric_name, metric.value)
        logger.debug("Submitting statsd metric: %s" % metric_string)

        if (not options.dry_run):
            udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            udp_sock.sendto(metric_string, (host[0], int(host[1])))
        else:
            print "%s %s" % (options.statsd_host, metric_string)


def start_locking(lockfile_name):
    """ Acquire a lock via a provided lockfile filename. """
    if os.path.exists(lockfile_name):
        raise LockingError("Lock file already exists.")

    f = open(lockfile_name, 'w')

    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write("%s" % os.getpid())
    except IOError:
        # Would be better to also check the pid in the lock file and remove the
        # lock file if that pid no longer exists in the process table.
        raise LockingError("Cannot acquire logster lock (%s)" % lockfile_name)

    logger.debug("Locking successful")
    return f


def end_locking(lockfile_fd, lockfile_name):
    """ Release a lock via a provided file descriptor. """
    try:
        fcntl.flock(lockfile_fd, fcntl.LOCK_UN | fcntl.LOCK_NB)
    except IOError, e:
        raise LockingError("Cannot release logster lock (%s)" % lockfile_name)

    try:
        os.unlink(lockfile_name)
    except OSError, e:
        raise LockingError("Cannot unlink %s" % lockfile_name)

    logger.debug("Unlocking successful")
    return

def parse(class_name, log_file, options):
    if (options.debug):
        logger.setLevel(logging.DEBUG)

    state_dir  = options.state_dir
    log_dir    = options.log_dir
    logtail    = options.logtail

    dirsafe_logfile = log_file.replace('/','-')
    logtail_state_file = '%s/logtail-%s%s.state' % (state_dir, class_name, dirsafe_logfile)
    logtail_lock_file  = '%s/logtail-%s%s.lock' % (state_dir, class_name, dirsafe_logfile)
    shell_tail = "%s -f %s -o %s" % (logtail, log_file, logtail_state_file)

    if class_name.find('.') == -1:
        # If it's a single name, find it in the base logster package
        class_name = 'parsers.%s.%s' % (class_name, class_name)

    logger.info("Executing parser %s on logfile %s" % (class_name, log_file))
    logger.debug("Using state file %s" % logtail_state_file)

    # Import and instantiate the class from the module passed in.
    module_name, parser_name = class_name.rsplit('.', 1)
    module = __import__(module_name, globals(), locals(), [parser_name])
    parser = getattr(module, parser_name)(option_string=options.parser_options)

    # Check for lock file so we don't run multiple copies of the same parser
    # simultaneuosly. This will happen if the log parsing takes more time than
    # the cron period, which is likely on first run if the logfile is huge.
    try:
        lockfile = start_locking(logtail_lock_file)
    except LockingError, e:
        logger.warning("Failed to get lock. Is another instance of logster running?")
        sys.exit(1)

    # Get input to parse.
    try:

        # Read the age of the state file to see how long it's been since we last
        # ran. Replace the state file if it has gone missing. While we are here,
        # touch the state file to reset the time in case logtail doesn't
        # find any new lines (and thus won't update the statefile).
        try:
            state_file_age = os.stat(logtail_state_file)[stat.ST_MTIME]

            # Calculate now() - state file age to determine check duration.
            duration = floor(time()) - floor(state_file_age)
            logger.debug("Setting duration to %s seconds." % duration)

        except OSError, e:
            logger.info('Writing new state file and exiting. (Was either first run, or state file went missing.)')
            input = os.popen(shell_tail)
            retval = input.close()
            if (retval != 256):
                logger.warning('%s returned bad exit code %s' % (shell_tail, retval))
            end_locking(lockfile, logtail_lock_file)
            sys.exit(0)

        # Open a pipe to read input from logtail.
        input = os.popen(shell_tail)

    except SystemExit, e:
        raise

    except Exception, e:
        # note - there is no exception when logtail doesn't exist.
        # I don't know when this exception will ever actually be triggered.
        print ("Failed to run %s to get log data (line %s): %s" %
               (shell_tail, lineno(), e))
        end_locking(lockfile, logtail_lock_file)
        sys.exit(1)

    # Parse each line from input, then send all stats to their collectors.
    try:
        for line in input:
            try:
                parser.parse_line(line)
            except LogsterParsingException, e:
                # This should only catch recoverable exceptions (of which there
                # aren't any at the moment).
                logger.debug("Parsing exception caught at %s: %s" % (lineno(), e))

    except Exception, e:
        print "Exception caught at %s: %s" % (lineno(), e)
        traceback.print_exc()
        end_locking(lockfile, logtail_lock_file)
        sys.exit(1)

    # Log the execution time
    exec_time = round(time() - script_start_time, 1)
    logger.info("Total execution time: %s seconds." % exec_time)

    # Set mtime and atime for the state file to the startup time of the script
    # so that the cron interval is not thrown off by parsing a large number of
    # log entries.
    os.utime(logtail_state_file, (floor(script_start_time), floor(script_start_time)))

    end_locking(lockfile, logtail_lock_file)

    # try and remove the lockfile one last time, but it's a valid state that it's already been removed.
    try:
        end_locking(lockfile, logtail_lock_file)
    except Exception, e:
        pass

    return (parser, duration)

def main(class_name, log_file, options):
    """
    Calls parse() and submit_stats()
    """
    (parser, duration) = parse(class_name, log_file, options)
    submit_stats(parser, duration, options)
