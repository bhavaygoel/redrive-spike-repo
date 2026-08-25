# dind_check — minimal Compose fixture for the TrueForge × Daytona DIND gate

Boring on purpose: one tiny HTTP app + PostgreSQL, ordinary Compose networking.

- `POST /webhook` `{"order_ref": "..."}` → 200 `{"id": N, "order_ref": "..."}` (inserts a row)
- `GET /health` → 200 only when Postgres is reachable
- No SQLite. No mocks.

Run: `docker compose up -d --build`, then hit `http://localhost:8092/webhook`.
App listens on 8092 inside the container.
