#!/usr/bin/python
#
# take a list of sites and check if they have changed since last visited
# if so output a well formed RSS document of items with links to the changed sites
#
# TODO: add support for specifying a diff method
#       eg. a method that uses a regex to grab part of the page and diff that
#       (like an image)
# TODO: add support for changing the content in an item
# TODO: allow options in the config to be overridden by the commandline

__author__ = 'Daniel Quinlan <daniel@chaosengine.net>'
__license__ = 'GPLv2'
__version__ = '1.1'

import ConfigParser
import cPickle
import email.Utils
import ezt
import httplib
import os
import pprint
import re
import rfc3339
import socket
import sys
import time
from optparse import OptionParser

try:
  # v2.5+
  import hashlib
  hash_func = hashlib.sha1
except ImportError:
  import sha
  hash_func = sha.sha

DEBUG_ENABLED = False

def DEBUG(message):
  if DEBUG_ENABLED:
    if isinstance(message, str):
      print >>sys.stderr, message
    else:
      pprint.pprint(message, stream=sys.stderr)

class EztRow(object):
  """Ezt is a PITA.  you can't use a dict, it expects an object."""

  def __init__(self, items):
   for key,value in items.iteritems():
     self.__setattr__(key, value)

class SiteChangeDetector(object):
  
  cache_dir = '/tmp'
  output_dir = '/tmp'
  output_file = 'site_changes'
  output_type = 'rss'
  max_items = 50
  page_title = 'Site Changes'
  page_link = 'http://localhost/'
  user_agent = 'Site Changes/%s' % __version__
  keep_content = False

  file_mode_exists = 'r+b'
  file_mode_new = 'wb'
  
  _urls = []
  _changed_urls = []
  _item_list_filename = 'site_changes.page_cache.for.%s' # % output_filename_basename
  _content_previous = 'site_changes.content.previous.%s' # % url_hash
  _content_current = 'site_changes.content.current.%s' # % url_hash

  def AddUrl(self, title, url, desc='', author=''):
    self._urls += (
	{'title': title,
	 'url': url,
	 'desc': desc,
	 'author': author,
	 },)

  def LoadFromFile(self, filename):
    config = ConfigParser.SafeConfigParser()
    config.read(filename)

    for section in config.sections():
      url = config.get(section, 'url')
      try:
	desc = config.get(section, 'desc')
      except ConfigParser.NoOptionError:
	desc = section
      try:
	author = config.get(section, 'author')
      except ConfigParser.NoOptionError:
	author = ''
      self.AddUrl(section, url, desc, author)

  def _GetPage(self, host, path):
    page = None
    # TODO: replace this with urllib2?
    conn = httplib.HTTPConnection(host)
    try:
      try:
	conn.request("GET", "%s" % path, None, {'User-Agent': self.user_agent})
	r1 = conn.getresponse()
	if r1.status == httplib.OK:
	  page = r1.read()
	else:
	  print "'%s%s' download failed: %s %s" % (host, path, r1.status, r1.reason)
      except Exception, msg:
	DEBUG("'%s%s' download failed: %s" % (host, path, msg))
    finally:
      conn.close()
    return page

  def Process(self):

    for index,site in enumerate(self._urls):
      url = site['url']
      url_hash = hash_func(url).hexdigest()
      cache_filename = os.path.join(self.cache_dir, 'site_changes.site.%s' % url_hash)
      content_previous = os.path.join(self.cache_dir, self._content_previous % url_hash)
      content_current = os.path.join(self.cache_dir, self._content_current % url_hash)
      DEBUG('\nworking on %s' % url)

      try:
	(protocol, junk, host, path) = url.split('/', 3)
      except ValueError, msg:
	DEBUG("bad config at line %d\n%s" % (index, msg))
	continue

      content = self._GetPage(host, "/" + path)
      if content == None:
        continue
      content_hash = hash_func(content).hexdigest()
      file_hash = self.ReadCache(cache_filename)

      if content_hash == file_hash:
	DEBUG('page unchanged')
	continue

      DEBUG('page changed')

      if self.keep_content:
	if os.path.exists(content_current):
	  os.rename(content_current, content_previous)
	self.WriteCache(content_current, content)

      self._changed_urls.insert(0, index)
      self.WriteCache(cache_filename, content_hash)

    DEBUG("\n")

  def ReadCache(self, file_name):
    abs_file_name = os.path.join(self.cache_dir, file_name)
    data = None
    try:
      DEBUG("read cache: %s" % abs_file_name)
      file_handle = open(abs_file_name, 'rb')
      data = cPickle.load(file_handle)
      file_handle.close()
    except (IOError, EOFError), err:
      DEBUG("failed to read cache %s: [%s] %s" % (abs_file_name, err.errno,
	err.strerror))
      data = None

    return data

  def WriteCache(self, file_name, data):
    abs_file_name = os.path.join(self.cache_dir, file_name)
    try:
      DEBUG("write cache %s" % abs_file_name)
      file_handle = open(abs_file_name, 'wb')
      cPickle.dump(data, file_handle)
      file_handle.close()
    except IOError, err:
      DEBUG("failed to write cache %s: [%s] %s" % (abs_file_name,
	    err.errno, err.strerror))
  
  def GeneratePage(self, output_filename, urls, page_title, page_desc,
      page_author):
    output_filename_basename = os.path.basename(output_filename)
    page_cache_filename = self._item_list_filename % output_filename_basename
    if self.output_type == "rss":
      change_time = email.Utils.formatdate(localtime=True)
    else:
      change_time = rfc3339.rfc3339(time.time())

    data = {'title': page_title,
	    'link': '%s%s' % (self.page_link, output_filename_basename),
	    'description': page_desc,
	    'date_822': change_time,
	    'author': page_author,
	   }

    data['item'] = self.ReadCache(page_cache_filename)
    if not data['item']:
      data['item'] = []
    DEBUG("item list len: %d" % len(data['item']))

    for index in urls:
      item = {'title': self._urls[index]['title'],
	      'url': self._urls[index]['url'],
	      'permalink': self._urls[index]['url'],
	      'date_822': change_time,
	      'content': 'Change detected on %s' % change_time,
	      'author': self._urls[index]['author'],
	      'categories': None, # TODO add this?
	      'enclosure': None, # TODO add scraping support?
	     }
      data['item'].insert(0, EztRow(item))

    # truncate rss items list to MAX
    data['item'] = data['item'][:self.max_items]

    self.WriteCache(page_cache_filename, data['item'])

    return data

  def WriteOutput(self, feed_per_site=False):
    template_name = '%spage.ezt' % self.output_type
    template_dir = os.path.join(os.path.dirname(__file__), 'templates')
    template = ezt.Template(os.path.join(template_dir, template_name))

    output_filename_base = os.path.join(options.output_dir, '%%s.%s' %
	options.output_type)

    if feed_per_site:
      output_files = {}
      for index in self._changed_urls:
	page_title = self._urls[index]['title']
	output_file = re.sub('[^\w\d._-]', '.', page_title.lower())
	output_file = output_filename_base % output_file
	output_files[output_file] = (page_title, self._urls[index]['desc'],
	    self._urls[index]['author'], (index,))
    else:
      output_files = {output_filename_base % self.output_file:
	  (self.page_title, self.page_title, None, self._changed_urls)}

    for (output_filename, data) in output_files.iteritems():
      page_title = data[0]
      desc = data[1]
      author = data[2]
      urls = data[3]
      data = self.GeneratePage(output_filename, urls, page_title, desc, author)

      output_file = open(output_filename, 'wb')
      try:
	DEBUG("writing output to %s" % output_file.name)
	template.generate(output_file, EztRow(data))
      finally:
	if output_file:
	  output_file.close()


if __name__ == '__main__':
  usage = "usage: %prog [options] <url | config file>"
  parser = OptionParser(usage=usage)
  parser.add_option("-d", "--cache_dir", dest="cache_dir",
                    metavar="DIR", default=SiteChangeDetector.cache_dir,
                    help="dir to store cache files [%default]")
  parser.add_option("-o", "--output_dir", dest="output_dir",
                    metavar="DIR", default="/tmp",
                    help="dir to write output files [%default]")
  parser.add_option("-f", "--output_file", dest="output_file",
                    metavar="FILE", default="site_changes",
                    help=("basename of output file.  extension is based on"
		          "--output_type. [%default]"))
  parser.add_option("-t", "--output_type", dest="output_type",
                    default=SiteChangeDetector.output_type,
		    help="output type: rss, atom [%default]")
  parser.add_option("--page_title", dest="page_title",
                    default=SiteChangeDetector.page_title,
		    help="Page title [%default]")
  parser.add_option("--page_link", dest="page_link",
                    default=SiteChangeDetector.page_link,
		    help="base url for the rss file [%default]")
  parser.add_option("--max_items", dest="max_items",
                    default=SiteChangeDetector.max_items,
		    help="maximum items to keep in feed [%default]")
  parser.add_option("--user_agent", dest="user_agent",
                    default=SiteChangeDetector.user_agent,
		    help="User-Agent header to send [%default]")
  parser.add_option("--keep_content", dest="keep_content",
                    action="store_true",
		    default=SiteChangeDetector.keep_content,
                    help="keep content of site [%default]")
  parser.add_option("--debug", dest="debug",
                    action="store_true", default=False,
                    help="print debugging info [%default]")
  parser.add_option("--feed_per_site", dest="feed_per_site",
                    action="store_true", default=False,
                    help="create a separate RSS feed per site [%default]")

  (options, args) = parser.parse_args()

  if not len(args) == 1:
    parser.error("you must specify a single url or a config file")

  DEBUG_ENABLED = options.debug

  detector = SiteChangeDetector()
  detector.cache_dir = options.cache_dir
  detector.output_dir = options.output_dir
  detector.output_file = options.output_file
  detector.output_type = options.output_type
  detector.page_title = options.page_title
  detector.page_link = options.page_link
  detector.max_items = options.max_items
  detector.user_agent = options.user_agent
  detector.keep_content = options.keep_content
  
  if args[0].startswith('http://'):
    detector.AddUrl(args[0], args[0])
  else:
    detector.LoadFromFile(args[0])

  detector.Process()
  detector.WriteOutput(options.feed_per_site)



