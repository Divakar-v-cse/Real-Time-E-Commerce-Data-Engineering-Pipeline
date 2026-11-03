import os
import sys

from common.db import fetch_all

sql = sys.argv[1]
for r in fetch_all(sql)[:25]:
    print(r)
