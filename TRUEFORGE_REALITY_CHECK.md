# TrueForge Reality Check — Redrive platform validation

**Date:** 2026-08-25 · **Timebox:** ~2h active · **Scope:** close the two platform risks left open by SPIKE_REPORT.md (TrueForge approval runtime, Daytona sandbox). Still a spike — no Redrive product code written.

**Environment:** TrueForge **v0.1.4** (`@truefoundry/trueforge`, npm), standalone local mode on `http://localhost:8790` (SQLite store, auth disabled). Model provider: custom OpenAI-compatible `opencode-go` (`base_url https://opencode.ai/zen/go/v1`), model `ox-alpha-free`. Sandbox provider: **Daytona** via Settings API → `status: ready`. Repo under test: `bhavaygoel/redrive-spike-repo`.

---

## Verdict: **PASS WITH PLATFORM CAVEAT**

Both load-bearing chains ran through TrueForge's actual runtime mechanisms end-to-end:

- **CHAIN A:** agent → custom MCP tool → **TrueForge native `tool.approval_required` pause** → GitHub provably unchanged → official-API approval → GitHub redelivery executes (202 → receiver 200 → business mutation exactly once).
- **CHAIN B:** agent → **TrueForge sandbox tool on real Daytona** → clone repo → checkout failing revision `e3157af` → replay the captured byte-exact real GitHub delivery → HTTP 500 + mutate-once → replay again → mutate-twice (danger proven); fixed revision `e86ce71` → 200/200, mutations=1.

Caveat (why not unqualified PASS): the TF-3 approval decision was submitted **programmatically through TrueForge's official `user.tool_approval` input** (operator away; pre-authorized in the task brief). The runtime created and enforced the pause itself; what remains unproven is only the human-click path in the chat UI, which is UI work, not platform risk.

**CORE PLATFORM RISK CLOSED. BUILD REDRIVE.**

---

## Gate matrix

| Gate | Result | Primary evidence |
|---|---|---|
| TF-1 TrueForge starts, real agent turn | **PASS** | session `01m0w76mz8yyztrwfejcf6ef3h`; output exactly `TRUEFORGE_TF1_OK`; metrics `{total_tokens:1478}` |
| TF-2 Redrive MCP through TrueForge | **PASS** | connector `redrive-github` (streamable-HTTP `http://127.0.0.1:8901/mcp`); agent natively invoked `get_webhook_delivery`; session `01m0w7y89rst1j8q8s7c88zbja`; `evidence_tf2.json` |
| TF-3 TrueForge-enforced approval | **PASS** | `tool.approval_required` event id `01m0w87d2w80484apkc5dny72n`; gated call `call_b5cccc51207d46eca0ea9825`; GitHub unchanged during pause; post-approval GitHub **202** + new delivery `3838959604597792768` (`redelivery:true`); full-chain rerun with live tunnel: delivery `3838960848873734144` → **HTTP 200**, mutations=1; `evidence_tf3.json`, `evidence_tf3b.json` |
| TF-4 Daytona provider via TrueForge | **PASS** | PUT `/settings/sandbox-providers` → `"status":"ready"` |
| TF-5 clone/checkout in Daytona | **PASS** | session `01m0wbj96p7smnfsm72dgyfd03`, sandbox `v1:daytona:default.ab6e2dfa-f2a9-42e9-8761-e635f8d94b33`; `git rev-parse HEAD` = `e3157afb085b0afa66d85a7e1b5917b08b824f91` |
| TF-6 exact failure reproduced in Daytona | **PASS** | same session; captured real delivery (HMAC-verified fixture, sha256 `593db193…`) replayed: **HTTP1=500 COUNT1=1, HTTP2=500 COUNT2=2** |
| TF-7 candidate invariant in Daytona | **PASS** | session `01m0wc3g4pyj4rsvxj475ne9ss`, sandbox `v1:daytona:default.6e8e020f-2b33-4cca-836e-a3be0f029986`; fixed rev `e86ce71`: **HTTP1=200 HTTP2=200, COUNT=1 LEDGER=1**, mutation row `(1,'44c70d9c-a06b-11f1-914c-d186f381ed14','order_payment_processed','…@d2af71adc3b9')`; `evidence_tf567.json`, `evidence_tf7_tokens.json` |
| Concurrent duplicate test (10× parallel) | **PASS w/ caveat** | codes `[ERR,200,ERR,200,…]`, **mutations=1 ledger_done=1** — invariant held; 8/10 clients got connection drops instead of clean no-op 200s (robustness bug, not a safety failure); `evidence_extra.json` |
| Invalid-signature rejection | **FAIL — fail-open confirmed** | bad sig `sha256=000…0`: buggy 500+mutates, fixed **200+mutates** (bad-sig-only runs, fresh DBs). Demo receiver must verify sig and reject before mutating |

Note: TF-7's turn terminal status was `cancelled` (harness cutoff after substantive completion); tokens were recovered from persisted `tool.response` exec outputs — evidence is from the TrueForge event store, not reconstructed locally.

---

## What was genuinely TrueForge-native

- Agent loop + turns streamed via TrueForge sessions API (SSE `turn.created/model.message/tool.response/sandbox.created/turn.done`).
- MCP connector registry: custom streamable-HTTP server registered via `/settings/mcp-servers`; deferred tool loading (`list_tools`/`get_tool_info`/`call_tool` harness wrappers visible in persisted events).
- Approval enforcement: `require_approval_for_tools: ["redeliver_webhook_delivery"]` on the agent spec's MCP server entry produced a real paused state (`required_actions`), resumable only via `user.tool_approval`. No JSON-shim, no custom gate logic anywhere.
- Sandbox-as-tool: every exec/file op in TF-5→7 executed inside Daytona microVMs provisioned by TrueForge (`sandbox.created` carries `v1:daytona:…` IDs); fixture entered the sandbox via TrueForge's own user-file upload path.
- Daytona provider lifecycle managed through the Settings API (key stored server-side, redacted in all reads).

## What still wasn't exercised

- Human Allow/Deny **click** in the chat UI (programmatic official-input approval used instead).
- Signature-validating receiver (fail-open found — fix belongs to the build).
- Clean concurrent no-op responses (invariant safe, UX rough).
- Local-fallback sandbox on this VM is broken (see friction) — irrelevant to the Daytona demo path.

## Platform friction

1. **Local fallback sandbox networking**: TrueForge's local SRT proxy (:34799) answers 407; pip installs inside local sandboxes fail ("Cannot connect to proxy"). Daytona path unaffected. Don't demo on local mode without fixing this layer.
2. **Large-ID mangling**: models emit webhook/delivery IDs as floats (`3.83…e+18`) → GitHub 404s. Fixed by coercive `as_int()` in the MCP server; product must keep this guard.
3. **Receiver port default is 8091**; a harness miswire produced a stray 502 redelivery record (excluded from chains).
4. **Daytona exec timeout** fired once at the default 60s during long compound steps; provider now set to 120s. Prefer small atomic commands.
5. One TF-7 turn ended `cancelled` after doing its work — treat turn status as advisory; read persisted exec outputs for truth.
6. `python3.12-venv` had to be installed for local-mode sandboxes to even bootstrap (apt).

## Recommendation

Stop evaluating alternatives. Both remaining platform assumptions survived contact with the real runtimes: TrueForge genuinely pauses gated MCP actions before execution, and its Daytona sandbox reproduces the exact production incident from the exact captured bytes, including the duplicate-replay danger and the candidate's exactly-once proof. Spend hackathon time on: signature fail-closed repair, concurrent no-op response handling, the human-click approval demo, and a named tunnel/deployed receiver.

---

### Artifact index (this directory)

`mcp_redrive_http.py` (Redrive MCP, streamable-HTTP) · `tf_driver.py` · `tf1_agent_turn.py` · `tf2_register_mcp.py` / `tf2_agent_call.py` · `tf3_approval.py` / `tf3_resume.py` / `tf3b_fullchain.py` · `tf4_configure_daytona.py` / `run_tf4.sh` · `tf567_sandbox_chain.py` · `extract_tf567.py` · `extra_checks.py` · `fixture_manifest.json` · `evidence_tf2.json`, `evidence_tf3.json`, `evidence_tf3b.json`, `evidence_tf567.json`, `evidence_tf7_tokens.json`, `evidence_extra.json`

Secrets: GitHub token (`.gh_token`), webhook secret, Daytona key (`.daytona_key`, 0600) are gitignored; keys were only ever sent to their own services (GitHub / Daytona / model provider) and are redacted in TrueForge API reads.
