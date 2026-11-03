import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import common  # noqa: F401  (adds vendor/ to sys.path)

import json
import psycopg2
from common.settings import PG_STATE_FILE

info = json.load(open(PG_STATE_FILE, encoding="utf-8"))
conn = psycopg2.connect(host=info["host"], port=info["port"], user=info["user"], dbname="postgres")
conn.autocommit = True
cur = conn.cursor()
cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", ("ecommerce",))
if not cur.fetchone():
    cur.execute("CREATE DATABASE ecommerce")
cur.execute("SELECT version()")
print("PG VERSION:", cur.fetchone()[0][:70])
conn.close()
