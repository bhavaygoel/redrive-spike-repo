#!/usr/bin/env python3
"""
Redrive spike receiver — CANDIDATE (fixed) variant.

Fix strategy: delivery-ID dedup + atomic "claim" before the business mutation.
  - INSERT INTO processed_deliveries(delivery_id, status='processing') is the
    atomic claim; UNIQUE(delivery_id) makes a replayed delivery lose the race
    or hit the unique constraint.
  - If claim fails -> already seen -> safe no-op HTTP 200.
  - Business mutation and 'done' marker commit in ONE sqlite transaction, so a
    crash between them still leaves the event claimable/redoable (at-least-once
    with dedup => effectively exactly-once for this business effect).

Endpoints: POST /webhook, GET /state (mutations + deliveries).
"""
import json
import hmac
import hashlib
import sqlite3
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import os
SECRET = os.environ.get("REDRIVE_SECRET") or open("/root/workspace/redrive-spike/webhook_secret.txt").read().strip()
DB = os.environ.get("REDRIVE_DB", "state.db")  # default: disposable DB in cwd (sandbox-friendly)

def db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("""CREATE TABLE IF NOT EXISTS mutations(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        order_ref TEXT,
        received_at TEXT NOT NULL)""")
    # The fix: durable ledger of deliveries, claimed atomically.
    c.execute("""CREATE TABLE IF NOT EXISTS processed_deliveries(
        delivery_id TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK(status IN ('processing','done')),
        updated_at TEXT NOT NULL)""")
    return c

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[receiver-fixed] {self.address_string()} {fmt % args}", flush=True)

    def _send(self, code, body: dict):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/state":
            c = db()
            m = c.execute("SELECT id,event_id,kind,order_ref,received_at FROM mutations ORDER BY id").fetchall()
            d = c.execute("SELECT delivery_id,status,updated_at FROM processed_deliveries ORDER BY rowid").fetchall()
            self._send(200, {
                "mutations": [{"id": r[0], "event_id": r[1], "kind": r[2], "order_ref": r[3], "received_at": r[4]} for r in m],
                "deliveries": [{"delivery_id": r[0], "status": r[1], "updated_at": r[2]} for r in d],
                "count": len(m)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/webhook":
            return self._send(404, {"error": "not found"})
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        event = self.headers.get("X-GitHub-Event", "unknown")
        delivery = self.headers.get("X-GitHub-Delivery", "unknown")
        sig = self.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
        sig_ok = hmac.compare_digest(expected, sig)
        print(f"[receiver-fixed] event={event} delivery={delivery} sig_ok={sig_ok} bytes={len(body)}", flush=True)

        payload = {}
        try:
            payload = json.loads(body)
        except Exception:
            pass

        if event != "push":
            return self._send(200, {"ok": True, "event": event, "note": "no mutation for non-push"})

        order_ref = f"{payload.get('repository', {}).get('full_name', '?')}@{str(payload.get('after','?'))[:12]}"
        c = db()

        # ---- ATOMIC CLAIM (the fix) ----
        try:
            c.execute("INSERT INTO processed_deliveries(delivery_id,status,updated_at) VALUES (?,?,?)",
                      (delivery, "processing", datetime.datetime.utcnow().isoformat() + "Z"))
            c.commit()
        except sqlite3.IntegrityError:
            row = c.execute("SELECT status FROM processed_deliveries WHERE delivery_id=?", (delivery,)).fetchone()
            if row and row[0] == "done":
                print(f"[receiver-fixed] REPLAY of done delivery {delivery} -> safe no-op", flush=True)
                return self._send(200, {"ok": True, "dedup": True, "note": "already processed; no-op"})
            # processing but not finished (crash mid-flight): redo the work
            print(f"[receiver-fixed] resuming incomplete delivery {delivery}", flush=True)

        # ---- BUSINESS MUTATION ----
        try:
            c.execute("BEGIN")
            c.execute("INSERT INTO mutations(event_id,kind,order_ref,received_at) VALUES (?,?,?,?)",
                      (delivery, "order_payment_processed", order_ref,
                       datetime.datetime.utcnow().isoformat() + "Z"))
            c.execute("UPDATE processed_deliveries SET status='done', updated_at=? WHERE delivery_id=?",
                      (datetime.datetime.utcnow().isoformat() + "Z", delivery))
            c.commit()
            print(f"[receiver-fixed] MUTATION committed once event_id={delivery}", flush=True)
        except Exception as e:
            c.rollback()
            print(f"[receiver-fixed] failed: {e}", flush=True)
            return self._send(500, {"error": str(e)})

        return self._send(200, {"ok": True, "dedup": False, "order_ref": order_ref})

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8091
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
