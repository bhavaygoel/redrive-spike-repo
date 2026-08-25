"""Smallest realistic webhook receiver for the DIND reality check.

Endpoints:
  GET  /health   -> {"status":"ok","db":"up"} (200 only if Postgres reachable)
  POST /webhook  -> inserts one row, returns 200 {"id": N, "order_ref": ...}
Env: PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE (supplied by Compose).
"""
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg2

PG = dict(
    host=os.environ.get("PGHOST", "db"),
    port=int(os.environ.get("PGPORT", "5432")),
    user=os.environ.get("PGUSER", "redrive"),
    password=os.environ.get("PGPASSWORD", "redrive_pw"),
    dbname=os.environ.get("PGDATABASE", "redrive"),
)

def query(sql, params=(), fetch=False):
    """Run one statement on its own connection; commit on success."""
    conn = psycopg2.connect(**PG)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall() if fetch else None
        conn.commit()
        return rows
    finally:
        conn.close()

def init_db():
    for attempt in range(60):
        try:
            query("""CREATE TABLE IF NOT EXISTS webhook_events(
                        id SERIAL PRIMARY KEY,
                        order_ref TEXT NOT NULL,
                        received_at TIMESTAMPTZ NOT NULL DEFAULT now())""")
            print("[app] db ready", flush=True)
            return
        except Exception as e:
            print(f"[app] waiting for db ({attempt}): {e}", flush=True)
            time.sleep(1)
    raise SystemExit("database never became ready")

class Handler(BaseHTTPRequestHandler):
    def _json(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path != "/health":
            return self._json(404, {"error": "not found"})
        try:
            query("SELECT 1")
            return self._json(200, {"status": "ok", "db": "up"})
        except Exception as e:
            return self._json(503, {"status": "degraded", "db": str(e)[:120]})

    def do_POST(self):
        if self.path != "/webhook":
            return self._json(404, {"error": "not found"})
        n = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        order_ref = str(data.get("order_ref", "unknown"))[:200]
        try:
            rows = query(
                "INSERT INTO webhook_events(order_ref) VALUES (%s) RETURNING id",
                (order_ref,), fetch=True)
            row_id = rows[0][0]
        except Exception as e:
            return self._json(500, {"error": str(e)[:200]})
        return self._json(200, {"id": row_id, "order_ref": order_ref})

    def log_message(self, fmt, *args):
        print("[app]", fmt % args, flush=True)

if __name__ == "__main__":
    init_db()
    ThreadingHTTPServer(("0.0.0.0", 8092), Handler).serve_forever()
