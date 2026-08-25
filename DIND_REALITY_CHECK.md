# DIND Reality Check — TrueForge → Daytona → Docker Compose

**Date:** 2026-08-25 · **Timebox:** ~70 min active · **Scope:** hard platform gate only — can a TrueForge-created Daytona sandbox support Docker-in-Docker + Docker Compose well enough to reconstruct an ordinary app+Postgres backend? No product code.

**Question under test:** `TrueForge agent → sandbox tool → Daytona sandbox → dockerd → docker compose → app+Postgres → HTTP → business row → independent SQL proof`

---

## Verdict: **PASS WITH CAVEAT — COMPOSE PATH WORKS, BUT DOCKER IS NOT PREINSTALLED AND MUST BE BOOTSTRAPPED BY THE AGENT AT RUNTIME**

The complete chain ran **through TrueForge's sandbox tool on real Daytona**: the agent installed Docker inside its own managed sandbox, started `dockerd`, cloned this repo, built and booted the Compose stack (`dind_check`: Python app + PostgreSQL 16), posted a webhook that inserted a row, proved the row via an independent `psql` query inside the Postgres container, then did a full `down`/`up` cycle and re-proved health + a second insert (row count 2).

Caveat (honest): TrueForge v0.1.4 provides **no image/snapshot selection** for Daytona sandboxes, so the stock sandbox image has **no Docker**; the agent bootstraps it at runtime (~2–4 min one-time per fresh sandbox). This is still fully TrueForge-native (every command flows through the TrueForge sandbox tool), but Redrive should either accept the bootstrap latency or lobby TrueFoundry for an image-override field / use a DIND-based snapshot once supported.

---

## Gate matrix

| Gate | Result | Evidence |
|---|---|---|
| DIND-1 TrueForge sandbox + docker/compose available | **PASS** | session `01m0xc760sspj9exsc93nc171s`, sandbox `v1:daytona:default.10f49dbc-39f9-44c6-834a-e300eb6048de`; after agent-run bootstrap: `docker version` → client+server **29.7.2**, `docker compose version` → **v5.5.0**. Stock image had no docker (`command not found`, exit 127) until provisioned |
| DIND-2 clone (not upload) | **PASS** | `git clone https://github.com/bhavaygoel/redrive-spike-repo.git` inside the sandbox; `GIT_SHA=577886a…` (fixture as pushed), later pulled forward to `6f607c6` |
| DIND-3 boot Compose | **PASS** | `docker compose up -d --build`; `compose ps`: `dind_check-app-1 Up (0.0.0.0:8092→8092)`, `dind_check-db-1 postgres:16-alpine Up (healthy)` |
| DIND-4 real app ↔ Postgres | **PASS** | `/health` → `{"status":"ok","db":"up"}`; `POST /webhook` → `APP_HTTP_CODE=200`, body `{"id":1,"order_ref":"dind-gate-test-1"}`; independent query inside db container: `DB_ROW_COUNT=1`, row `(1, dind-gate-test-1, 2026-08-25 21:35:14.768831+00)` |
| DIND-5 restart reliability | **PASS** | `docker compose down && up -d` → both containers healthy again; `COLD_SECONDS=23`; post-restart `/health` ok, second webhook `200` (`id 2`), `ROWS_AFTER_RESTART=2` |

Machine tokens (verbatim from the TrueForge turn transcript): `DOCKER_VERSION=29.7.2 29.7.2` · `COMPOSE_VERSION=Docker Compose version v5.5.0` · `GIT_SHA=6f607c6` · `APP_HTTP_CODE=200` · `DB_ROW_COUNT=1` · `COLD_SECONDS=23` · `SECOND_POST_CODE=200` · `ROWS_AFTER_RESTART=2`

## Exact runtime path (what Redrive should standardize)

1. TrueForge v0.1.4 standalone; agent spec `{model, config.sandbox.enabled:true}`; provider = Daytona (`status: ready`, key stored server-side).
2. TrueForge clones every sandbox from its release-owned snapshot (`tfy.jfrog.io/tfy-images/trueforge-sandbox:<sha>`) — **there is no user-facing image/snapshot field** (verified in OpenAPI + source: `sandboxImage` comes only from internal build metadata).
3. Therefore DIND is achieved **in-sandbox via the agent**: `curl -fsSL https://get.docker.com | sh` → `nohup dockerd &` → normal `docker compose`. All of it executes through the TrueForge sandbox tool on Daytona (Debian 12, x86_64). Nothing was run against host Docker; nothing bypassed TrueForge.
4. Sandbox state persists across turns within one session (Docker install, repo clone, images, volumes all survived four turns). It does **not** persist across sessions — a new session gets a brand-new sandbox.

## What was genuinely TrueForge-native vs debugging

- Native (counts as PASS): every gate command above ran inside the TrueForge-managed Daytona sandbox via agent tool calls; evidence read back from the persisted TrueForge event store.
- Debug-only (did not count toward PASS): none needed at the Daytona layer — the two mid-run failures were fixture bugs (see friction), diagnosed *by the agent itself* from container logs.

## Friction Redrive must account for

1. **No preinstalled Docker**: budget ~2–4 min first-turn provisioning (apt install + dockerd start) per fresh sandbox. A custom Daytona DIND snapshot (`docker:28.3.3-dind` base per Daytona docs) would eliminate this — blocked only by TrueForge's missing override field (candidate upstream ask; Daytona itself officially supports DIND, recommends ≥2 vCPU/4GiB).
2. **dockerd lifecycle**: must be (re)started if the sandbox auto-stops/archives between turns; keep `auto_stop_interval` generous during long rebuilds.
3. **First build pulls base images** (python slim + postgres alpine) inside DIND — adds ~1–2 min; subsequent builds hit the in-sandbox cache within the same session.
4. **Session-scoped sandboxes**: "resume" requires continuing the same TrueForge session; a new session = new sandbox from scratch (cost us one wasted run).
5. **Agent honesty is load-bearing**: the agent refused twice to fabricate token outputs when the fixture was broken (build-context bug `577886a` → fixed `80c3c63`; psycopg2 connection.execute bug → fixed `6f607c6`). Keep the "print exact errors, never fabricate" instruction in Redrive's harness prompts.
6. Pending `ask_user_question` blocks plain messages (HTTP 422); resume via official `user.tool_response` input.

## Recommendation

Standardize Redrive on exactly what passed: TrueForge standalone/hosted + Daytona provider + agents with `sandbox.enabled`, and a first-turn "environment bootstrap" step (`get.docker.com | sh` + `dockerd`) baked into the Redrive playbook. File a TrueForge feature request for a sandbox image/snapshot override (Daytona DIND snapshots) to cut cold-start to seconds. Compose-based environment reconstruction is viable for the product.

Evidence files: `dind_check/evidence/evidence_dind_chain.json`, `evidence_dind_resume.json`, `evidence_dind_resume2.json`, `evidence_dind_resume3.json`, `evidence_dind_resume4.json`, `dind_transcript_excerpt.md`.
