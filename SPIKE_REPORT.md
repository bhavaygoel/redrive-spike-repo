# Redrive Technical Spike Report

**Date:** 2026-08-25 · **Timebox:** ~90 min actual · **Scope:** viability spike, not product build
**Question:** Can the core Redrive loop work using *real* external webhook delivery + MCP + sandbox + approval gating?

---

## Verdict: **PASS WITH CAVEATS**

The central loop is clean and every hard primitive was demonstrated against real GitHub infrastructure.
The two caveats are environmental, not conceptual:

1. **TrueForge/Daytona were not live-exercised** (user directive mid-spike: skip them *if we can assume they work as intended*). Their advertised capabilities match our needs exactly (MCP tools, `require_approval_for_tools`, Daytona-backed sandbox-as-tool), so the assumption is reasonable — but the integration is unproven. First hour of the hackathon should be a TrueForge smoke test.
2. The **approval pause was emulated faithfully at the API boundary** (execution provably blocked until an approval record existed, automated operator approved). A human-click demo through TrueForge's chat UI remains to be shown.

Nothing discovered suggests a fundamental flaw in the Redrive concept.

---

## Gate matrix

| Gate | Result |
|---|---|
| 1 · Real failed GitHub delivery | **PASS** |
| 2 · Exact delivery retrieval via API | **PASS** |
| 3 · Sandboxed reproduction of the exact failure | **PASS** (with fidelity notes) |
| 4 · Replay-safety proof (danger + fix) | **PASS** |
| 5 · Approval-gated real redelivery via custom MCP | **PASS** (shimmed gate; documented) |
| Final dual verification (2xx + exactly-once) | **PASS** |

---

## Evidence

### Gate 1 — real failed delivery
- Repo: `bhavaygoel/redrive-spike-repo` (disposable, public), fix commit later pushed as `e86ce71`
- Hook ID: **670245925** → `https://oasis-lamb-remain-broad.trycloudflare.com/webhook` (cloudflared quick tunnel)
- Event triggered by real `git push` (`d2af71a`): receiver v1 committed the business mutation, then simulated downstream crash
- **Delivery ID: `3838950303252611072`** · GUID `5558bf00-a068-11f1-93e3-0cea5052a583` · event `push`
  - `delivered_at: 2026-08-25T09:35:40.128Z` · **HTTP 500** recorded by GitHub (`status: "500 "`)
  - ping delivery `3838950288312500224` → 200 (control)
- Receiver SQLite at that moment: `mutations count = 1`, row `(event_id=5558bf00…, order_ref=bhavaygoel/redrive-spike-repo@d2af71adc3b9)`
- ⇒ Provider says FAILED while business state already changed. Exactly the incident class Redrive targets.

### Gate 2 — reconstructing the exact failed delivery
`GET /repos/{o}/{r}/hooks/{id}/deliveries/{delivery_id}` returns:
- id, GUID, event, status_code, delivered_at, `redelivery` flag, throttled_at, duration
- **full request headers** including original `X-Hub-Signature-256` and `X-Hub-Signature`, User-Agent `GitHub-Hookshot/413197b`
- **full request payload** (JSON object in API response)
- **response body the receiver returned**: `{"error": "downstream payment-notify service unavailable (simulated)", …}`
- attempt history via the deliveries list (`redelivery: false/true` flags)

**Byte-exactness proof:** payload comes back as a JSON object; re-serializing with compact separators (`,`/`:`) reproduces the original wire bytes — HMAC-SHA256 over those bytes **matches GitHub's stored `X-Hub-Signature-256`** (`sha256=47088636e24a8c55…`). So the replay fixture is cryptographically verified, not assumed.

**Answer:** YES — enough to reconstruct a faithful replay fixture entirely from API evidence. Stock TrueForge GitHub MCP does not expose hook-delivery endpoints; a ~90-line custom stdio MCP server around the REST API covers it (built and used below).

### Gates 3+4 — sandbox reproduction & replay-safety matrix
Isolated sandbox per variant (fresh dir, fresh disposable SQLite, "checkout" of that revision), replaying the **captured real delivery** (byte-exact body, recomputed valid signature, same event/delivery headers):

| Receiver | Attempt 1 | Replay of same delivery |
|---|---|---|
| BUGGY (v1) | HTTP **500**, mutations **1** | HTTP **500**, mutations **2** ❌ duplicate side effect |
| FIXED (candidate) | HTTP **200**, mutations 1, ledger done=1 | HTTP **200 no-op**, mutations **still 1** ✅ |

Invariant measured from the database, not asserted. Local rehearsal with a synthetic fixture produced identical numbers before the real capture existed.

**Fidelity statement:** payload/business behavior fidelity = byte-exact (HMAC-proven); header semantics preserved (event, delivery GUID, signature valid against secret); transport = local loopback HTTP rather than GitHub→tunnel TLS edge. Signature header had to be recomputed for replays even though GitHub returns the original (replay requests are constructed by us; GitHub's own redelivery re-signs automatically — see Gate 5).

### Gate 5 + Final — approval-gated real redelivery
Custom MCP server exposes `redeliver_webhook_delivery(hook_id, delivery_id)` → `POST /repos/{o}/{r}/hooks/{id}/deliveries/{d}/attempts`.

- Phase A: approval requested → status `pending` → tool call attempted → **BLOCKED** ("approval status='pending'; execution blocked"). GitHub deliveries list compared before/after: **identical** — no request left the machine.
- Phase B: approval record written by **AUTOMATED TEST OPERATOR** (spike-only; real demo must use a human click in TrueForge chat UI) → same call executed → GitHub API returned **202**
- GitHub recorded a new delivery: id `3838951875992887296`, **same GUID** `5558bf00…`, `redelivery: true`, **HTTP 200**
- Receiver state after: `mutations = 1` (exactly once), ledger `5558bf00… → done`

**BEFORE/AFTER summary**

```
BEFORE  delivery 3838950303252611072  HTTP 500   business mutation = 1   blind replay would double it
AFTER   same delivery redriven        HTTP 200   business mutation = 1   exactly-once proven
```

Note: a `502` delivery (`3838951636103864320`) appears in the log — spike-harness artifact (a probe sent during a redeploy gap when no listener was up). It created no business mutation and is excluded from the flagship chain.

---

## What was REAL vs SIMULATED

**Real:**
- GitHub webhook creation, push event, failed delivery recording (provider side 100% genuine)
- Delivery retrieval incl. payload, original signatures, response body (official REST API)
- Cryptographic verification that our replay fixture is byte-identical to the original wire payload
- Public HTTPS transport into this machine (Cloudflare quick tunnel) for the original failure
- GitHub's official redelivery operation (202 + `redelivery: true` record + fresh attempt hitting our receiver over the internet)
- Business-state ledger and dedup logic (real SQLite, measured)

**Simulated / shimmed (explicitly):**
- The failing "downstream service" after the mutation is a raised exception (that's the incident model itself, fine)
- Sandbox = isolated local directories + disposable SQLite, NOT Daytona microVMs (per user directive)
- Approval gate = explicit two-phase policy shim at the tool-call boundary with persisted approval records, NOT the TrueForge runtime's `require_approval_for_tools` path (same contract; different enforcement point)
- MCP server = custom minimal stdio implementation, run standalone (not loaded inside a TrueForge agent session)
- Final redelivery reached the fixed receiver through the same tunnel; the receiver itself runs on this box (not in a remote sandbox)

---

## Friction / limitations encountered

- **GitHub API quirk:** delivery payload returns as JSON object; naive re-serialization breaks signature equality — compact separators reproduce wire bytes. Wrap this once in the product's fixture builder.
- **No stock MCP** exposes hook-delivery read/redelivery → tiny custom MCP required (~90 lines, already written). Acceptable and clean.
- **Token scope:** device-flow OAuth (GitHub CLI app) with `repo, admin:repo_hook` sufficed. No PAT stored on machine prior; SSH key alone cannot read webhooks API.
- This VM: **aarch64** (x86_64 binaries fail with Exec-format error), no `sqlite3` CLI (use Python module), browser automation daemon currently broken, cloudflared quick-tunnel URL is ephemeral per restart.
- GitHub retains delivery payloads for a limited window (docs say up to 30d for active hooks) — Redrive's fixture store should persist captures itself.
- Rate limits: unauthenticated 60/h vs authenticated 5k/h — product must always use authed calls.

## Answers to the 10 questions

1. **Yes** — full payload + headers + response + attempt flags via `/hooks/{id}/deliveries[/{id}]`; fixture byte-exactness provable via stored signature.
2. **Yes** — `POST …/deliveries/{id}/attempts` → 202; observed `redelivery:true` delivery arriving at our endpoint.
3. **Yes-by-design** — tool wrapped in custom MCP; gate semantics proven at the boundary. Live TrueForge `require_approval_for_tools` wiring still to be demonstrated (caveat #1).
4. **Yes locally** (minutes, zero overhead). Daytona spin-up time/ergonomics unmeasured (caveat #1).
5. **Yes** — captured real event reproduced 500 + mutate-once in an isolated env.
6. **Yes** — replay against buggy rev: mutations 1→2, measured in DB.
7. **Yes** — candidate fix: same event twice → 200/200, mutations stay 1; ledger backfill handles pre-fix deliveries (real repair insight).
8. **Yes** — original delivery redriven post-repair; GitHub 202 → receiver 200.
9. **Yes** — independent proofs: provider-side HTTP status from GitHub's records AND receiver-side SQL counts.
10. See the real/simulated table above.

---

## Intended production/demo path (post-spike)

1. Stand up TrueForge (local mode) + connect model + register custom `github-webhook-redrive` MCP server + Daytona sandbox config.
2. Agent session: given hook/delivery id → MCP `get_failed_delivery` → builds HMAC-verified fixture → spins Daytona sandbox → clones repo, checks out failing SHA, replays, observes failure → proposes patch → sandbox replay-matrix proves invariant → asks human.
3. Human clicks Approve in TrueForge chat (`require_approval_for_tools`) → `redeliver_webhook_delivery` executes → agent verifies dual proof (GitHub status + receiver ledger) and emits the recovery receipt.
4. Demo hardening: named tunnel or deployed receiver (Fly/Render), persistent fixture store, human-in-the-loop approval only.

## Recommendation

**Commit the hackathon to Redrive.** Every load-bearing primitive of the loop survived contact with the real GitHub API; nothing needed hand-waving. Spend the first hour de-risking the only untested links (TrueForge approval UX end-to-end, Daytona boot latency), keep the custom MCP + fixture-builder code (already in `/root/workspace/redrive-spike/`), and build the demo around the exact flow above. If TrueForge's approval click or Daytona startup proves hostile within that first hour, fall back to the documented shim paths — the concept itself has no known flaw.
