#!/usr/bin/python
#

import site_changes

import sys

  
file_name = sys.argv[1]
data = site_changes.ReadCacheFile(sys.argv[1])
fh = open("%s.out" % file_name, 'wb')
fh.write(data)
fh.close()
