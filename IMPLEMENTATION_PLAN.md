# Implementation Plan — Secure Loan Verification Demo (SLVD)
**Replication of the "HumanGuided AI – Secure Loan Verification on HPE Private Cloud AI" video demo**

- Workspace: `~/projects/secure_loan_verification_demo`
- Target platform: **CS1 (HPE Private Cloud AI)** via Helm + EzAppConfig + Istio VirtualService
- Doc version: v1.1 (2026-09-12) — gap review §16 completed (12 findings: 10 fixed, 2 accepted+mitigated)
- Status: PLAN — reviewed, approved-for-execution (awaiting user GO to start the autonomous loop)

---

## 0. How to use this document

- §1–2: what we build and the verified ground truth it stands on.
- §3–8: architecture, component specs, contracts, deployment design.
- §9–10: testing strategy and the defect-free acceptance gate.
- §11: the **autonomous development loop** (build → test → review → fix → deploy → verify, no manual intervention).
- §12–15: milestones, risks, deliberate deviations, rollout procedure.
- §16: gap review of this plan (findings + resolutions).

Every acceptance item in §10 is machine-checkable (script or curl) so the loop in §11 can self-verify.

---

## 1. Objective & definition of success

Replicate the video demo as a **working, interactive, deployed application** on CS1 such that:

1. A risk analyst (Nick Johnson, E102938) opens the **Credit Risk Portal**, selects case **CR-2026-00451** (Acme Industrial Holdings, $5,000,000 renewal), clicks **Generate renewal decision memo**.
2. A governed AI agent (**credit-memo-agent**, NemoClaw/OpenClaw in an OpenShell sandbox) runs the 10-step governed workflow: pulls data from 5 governed back-office systems (CRM, Credit exposure, Transactions, Compliance, Prior memos) via the governed MCP `credit-memo-mcp`, analyzes, and drafts the memo.
3. Policy engine triggers (**amount ≥ $5M** and/or **KYC pending**) → workflow **pauses** at "Approval decision" → **approval email** is sent to senior officer Sarah Chen (E200145) with full context (request ID, user, agent, tool, reason, Approve-8h / Approve-24h / Reject buttons).
4. Sarah approves via the signed email link (or Admin dashboard) → decision **timestamped in audit log** → workflow resumes → memo **published** to `/official/credit/2026/CR-2026-00451` → run **Completed** (Run ID `RUN-…`).
5. Client notification **"Loan Application Approved"** issued.
6. All of the above is **observable** in the portal: Workflow Progress (10 steps), Generated Memo (video-identical content), Governance Review card (request UUID, Re-submit button), Run Summary + Audit Trail (7 entries).

**Definition of "done"**: §10 acceptance gate 100% green, zero open P0/P1 defects, verified by the autonomous loop (§11) with full iteration logs — not by claim.

---

## 2. Ground truth (verified live on CS1, 2026-09-12)

| Fact | Value |
|---|---|
| Cluster | CS1, domain `aie.cs1.ctc.sg.lab`, kubeconfig `/home/ml/projects/kubeconfig-cs1.conf` |
| NemoClaw release | `nemoclaw` in ns `nemoclaw`, pod 2/2 Running (openclaw sandbox image `ghcr.io/nvidia/openshell-community/sandboxes/openclaw@sha256:b3d8…` + istio proxyv2 sidecar), VS host `nemoclaw.aie.cs1.ctc.sg.lab` via gateway `istio-system/ezaf-gateway` |
| LLM proxy | litellm svc `litellm-helm.project-user-aieadmin.svc.cluster.local:4000`, master key in secret `litellm-helm-masterkey` (ns `project-user-aieadmin`), model `qwen3-8-27b-int4-dflash2` (reasoning model → always `max_tokens ≥ 256`) |
| Chartmuseum | `http://chartmuseum.ez-chartmuseum-ns.svc:8080` — **ClusterIP-only, no VS** → push via `kubectl port-forward` (§8.1) |
| Storage classes | `nfs` / `nfs-csi` (default) / `rook-ceph-block` → slvd-data PVC uses default `nfs-csi` |
| Local tooling | docker 29.1.3, python 3.11.15, node v26.1.0 (portal build), `hermes` CLI (autonomous loop workers), git → push to `mlyu2000` |
| EzAppConfig pattern | CR `ezappconfigs.ezconfig.hpe.ezaf.com` in ns `ui`; static `endpoint` allowed; delete CR → verify no orphans → re-deploy |
| Registries pullable by CS1 nodes | `registry.ctc.sg.lab:5000` (local, preferred), `ghcr.io`, `docker.io`, `quay.io`, `registry.k8s.io` |
| Storage | Rook/Ceph CSI (ceph v18, cephcsi v3.12.3) + NFS CSI (default `nfs-csi`) available → PVCs work |
| Istio | Sidecars injected on `nemoclaw` ns pods; internal plain-HTTP gateway→sidecar can 503 (known CS1 behavior) → slvd workloads will opt out of sidecar injection (`sidecar.istio.io/inject: false`) except where the VS needs it; external access only via VS |
| Standing user constraints | Only modify our own charts/EzAppConfig (no platform config changes); 1 pod per component; external HTTPS URL must be browser-reachable (no internal bypass); chart version bumped per iteration; no secrets committed |

---

## 3. Solution architecture

```
                        ┌────────────────────────── CS1 cluster ──────────────────────────┐
 Browser (analyst)      │                                                                  │
 ┌────────────┐  HTTPS  │  ┌─────────┐   ┌──────────────┐   ┌────────────────────────┐    │
 │ Analyst     │────────▶│  │ VS:     │──▶│  portal      │──▶│  workflow-engine       │    │
 │ Nick J.     │  :443   │  │ slvd.   │   │  (React)     │   │  (FastAPI, FSM, SSE,   │    │
 │ approver    │         │  │ aie.cs1 │   │  5 screens   │   │   policy, audit, docs) │    │
 │ Sarah C.    │  HTTPS  │  └─────────┘   └──────────────┘   └───────┬──────────────┘    │
 └────────────┘──────────│      ▲                                    │ 1) prompt agent    │
      │ approval link    │      │ SSE / REST                          │ 2) store memo      │
      ▼                  │  ┌───┴───────────┐   ┌────────────────┐    │ 3) policy check   │
 ┌────────────┐  signed  │  │   engine      │   │  credit-memo-  │    │ 4) pause+email    │
 │  mailpit    │◀─────────│  │   API        │◀──│  mcp (FastMCP  │    │ 5) resume+publish │
 │ (SMTP+web)  │  SMTP    │  └──────────────┘   │  + REST, mock   │    └──────────────────┘    │
 └────────────┘         │                       │  back-office)  │                            │
                        │                       └───────▲────────┘                            │
                        │        ┌──────────────────────┼──────────────────────┐              │
                        │        │  agent (nemoclaw release, ns nemoclaw)      │              │
                        │        │  credit-memo-agent = OpenClaw + LLM         │              │
                        │        │  (litellm→qwen3-8-27b-int4-dflash2)         │              │
                        │        │  tools: credit-memo-mcp (MCP streamable HTTP)│             │
                        │        └─────────────────────────────────────────────┘              │
                        │   + mailpit (client "Loan Approved" mail)                           │
                        └──────────────────────────────────────────────────────────────────────┘
```

**Key design decisions**

1. **Agent-driven workflow (faithful to the video)**: the portal does NOT call back-office systems directly. It asks the workflow-engine to start a governed run; the engine prompts the **agent**, which pulls data through the **governed MCP** (the single authorized gateway to data), drafts the memo with the LLM, and calls `workflow__submit_credit_memo`. The engine supervises, applies policy, pauses/resumes, audits, publishes.
2. **Two governance points** (mirroring the video): (a) MCP server enforces identity-scoped data access (analyst token → only their data); (b) engine policy engine enforces the approval gate (the "Access Request" email).
3. **Reuse, don't rebuild**: agent runtime = existing `nemoclaw` release (add MCP registration to its openclaw.json ConfigMap — a chart values/ConfigMap patch, still within "our charts"). Everything new ships in one new chart `slvd`.
4. **Simulation mode**: env `SLVD_SIMULATION=1` auto-approves the approval gate after a configurable delay (default 8s) and uses a deterministic memo stub when `SLVD_LLM=0`. This is what the autonomous loop's e2e uses (unattended); production mode uses the real agent + real email.
5. **Mailpit** for email (dev-standard webmail + SMTP); the video itself used Mailpit. Production swap = SMTP relay (documented deviation, §14).

---

## 4. Component specifications

### 4.1 `portal` — Credit Risk Portal (React + Vite + TS)
Single SPA, 5 screens (one per video frame), pixel-close styling (dark navy header, white cards, Inter font, green check/pause icons):

| # | Screen | Content (verbatim from video) |
|---|--------|-------------------------------|
| 1 | **Analyst Portal** | Session info: Logged in as **Nick Johnson**, Role **Risk Analyst**, Department **Credit Risk**, Employee ID **E102938**. Case Selection: Case ID dropdown (**CR-2026-00451**), Client **Acme Industrial Holdings**, Type **Renewal Decision Memo**, Amount **$5,000,000** (editable, pre-filled — SRT: "select a case ID and enter the loan requested amount… In this case, $5 million"; validation: positive number, drives policy threshold). Button: **Generate renewal decision memo**. "HOW THIS WORKS" explainer text (video copy). |
| 2 | **Workflow Progress** | "Governed run in progress…" banner + 10 steps: Identity validated / Case metadata resolved / CRM profile fetched / Credit exposure fetched / Transaction behavior analyzed / Compliance status checked / Prior memo reviewed / Draft memo created / Submission attempted / Approval decision. Live via SSE. |
| 3 | **Generated Memo** | "Client: Acme Industrial Holdings (CL-77821) Renewal Request"; Overview: requested $5,000,000; utilization $3,800,000 (76% of limit); Revolving credit; Risk rating **BB**; In compliance with covenants. Key Considerations: 1) Stable transaction history with no delinquencies 2) Pending KYC review (beneficial ownership update required) 3) Prior memo conditions: Quarterly reporting and no additional unsecured borrowing 4) Open follow-up: Collateral valuation update needed. |
| 4 | **Governance Review In Progress** | Request ID (UUID), "The governance team has been notified. This page will automatically continue once approval is granted, or you can re-submit manually after approval." Button: **Re-submit (Approved)** — visible while awaiting (as in the video); enabled once a decision is recorded (click = force resume); while still pending it re-checks status. Also shown on reject (label "Re-submit") with a fresh request UUID after re-submission. |
| 5 | **Run Summary + Audit Trail** | Status **Completed**; Case ID; Run ID `RUN-NNNNN`; Requested by Nick Johnson (E102938); Approved by Sarah Chen (E200145); Approval Role Senior Credit Officer. Audit entries: Identity validated — Nick Johnson (Risk Analyst) / Case resolved — CR-2026-00451 (Acme Industrial Holdings) / Systems accessed — CRM, Credit, Transactions, Compliance, Prior Memos / Draft memo saved to /drafts/credit/CR-2026-00451 / Policy triggered — approval required (KYC pending + amount ≥ $5M) / Approved by Sarah Chen (Senior Credit Officer) / Memo published to /official/credit/2026/CR-2026-00451. |

Plus: **Agent Chat** sidebar (all screens) — placeholder "Ask questions about cases, clients, or credit policies. You can also ask the agent to generate a memo." + input "Ask about a case, client, or request a memo…" (implemented as a thin chat to the agent via engine `/api/chat`; non-blocking for the gate). Header: gear + "Credit Risk Portal", session email, **Logout**.

### 4.2 `engine` — workflow-engine (Python 3.11 + FastAPI + SQLAlchemy/SQLite-on-PVC)
- **FSM**: 10-step run state machine, states `PENDING→RUNNING→AWAITING_APPROVAL→COMPLETED|REJECTED|FAILED`; illegal transitions rejected (unit-tested).
- **REST**: `POST /api/runs` (start; body: case_id, amount, user_token) · `GET /api/runs/{id}` · `GET /api/runs/{id}/events` (SSE) · `GET /api/runs/{id}/memo` · `GET /api/audit/{run_id}` · `POST /api/approvals/{request_id}/decision` (decision=approve|reject, ttl=8h|24h, signed) · `POST /api/approvals/{request_id}/resubmit` · `POST /api/chat` (proxy to agent) · `GET /healthz` · `GET /api/runs` (list).
- **Agent orchestration**: on run start → validate identity (JWT) → resolve case → prompt credit-memo-agent (OpenClaw HTTP API) with the case payload; track MCP tool-call events reported back by the MCP server (webhook → engine `/api/internal/tool-events`) to advance the 6 data steps; memo returned by agent → saved to `/data/docs/drafts/credit/<case>/memo.md` → **policy evaluation** → if approval required: create approval request (UUID), email Sarah (signed link, 24h expiry), state `AWAITING_APPROVAL`; on decision: record timestamped audit entry, resume → publish to `/data/docs/official/credit/2026/<case>/memo.md` → client notification email → `COMPLETED`.
- **Policy engine** (pure function, unit-tested): `needs_approval(amount, kyc_status) = amount >= 5_000_000 or kyc_status == "pending"`.
- **Audit**: append-only table (ISO-8601 UTC timestamps, immutable — UPDATE/DELETE disabled at schema level) + JSONL mirror.
- **Documents**: SQLite-adjacent file store on PVC (`/data/docs`), path layout exactly as the video (`/drafts/credit/…`, `/official/credit/2026/…`).
- **Identity**: issues/verifies HS256 JWTs (demo login: Nick Johnson / Sarah Chen with fixed passwords, documented). Approval links: HMAC-SHA256 signed (engine secret) + 24h expiry + single-use (decision idempotent; double-click returns same recorded decision).
- **Simulation mode** (`SLVD_SIMULATION=1`): auto-approves after `SLVD_SIM_APPROVE_DELAY` (default 8s); `SLVD_LLM=0` uses deterministic memo stub (no LLM) — both flags ON for the loop's e2e; OFF for final golden run.

### 4.3 `mcp-server` — credit-memo-mcp (Python 3.11, FastMCP over streamable-HTTP + REST fallback)
- **Tools** (governed; each requires analyst identity token): `get_crm_profile(case_id)` · `get_credit_exposure(case_id)` · `get_transactions(case_id)` · `get_compliance_status(case_id)` · `get_prior_memo(case_id)` · `workflow__submit_credit_memo(case_id, memo_md, decision)` — the governed method that triggers the access-request flow.
- **Mock back-office data**: JSON fixtures in `mockdata/` for Acme (values exactly as the video memo: utilization $3.8M/76%, BB, covenant-compliant, KYC pending, prior conditions, collateral follow-up) + 2 secondary cases (CR-2026-00452 $2M clean → no approval; CR-2026-00453 $2M KYC-pending → approval) for scenario tests.
- **Governance**: token → allowed case set (Nick: 451/452/453); every tool call emits `{tool, case_id, actor, ts, ok}` webhook to engine → drives the 6 "fetched/analyzed" workflow steps (video's "securely pulling the data I'm allowed to see").
- **`workflow__submit_credit_memo`**: returns `{status:"approval_required", request_id, reason}` when policy triggers, else `{status:"published"}` — the engine then acts.
- **REST mirror** (`/tools/<name>`) so the agent can also call via plain HTTP if MCP transport is unavailable (risk mitigation, §13 R6).

### 4.4 `agent` — credit-memo-agent (NemoClaw/OpenClaw in the existing `nemoclaw` release)
- **Two agent backends (engine-configurable, `SLVD_AGENT_BACKEND=openclaw|direct_llm`)**:
  - **`openclaw`** (video-faithful): patch the nemoclaw ConfigMap `openclaw.json` — add `mcp.servers.credit-memo-mcp = {url: "http://credit-memo-mcp.slvd.svc:8000/mcp", transport: "streamable-http"}` (exact schema verified at M2 against the live openclaw config format; keep litellm provider, `max_tokens` ≥ 2048). Engine calls the agent via the OpenClaw gateway HTTP API (svc/port discovered at M2, expected `http://nemoclaw-nemoclaw.nemoclaw.svc:18789` + token).
  - **`direct_llm`** (fallback F1, also the default until M2 proves openclaw e2e): engine itself runs the agent loop — system prompt + OpenAI function-calling against litellm, tools = mcp-server REST mirror. Same system prompt, same validator, same audit. This removes LLM-client/transport risk (R5/R6) from the critical path; the OpenClaw dashboard stays live for chat parity (Agent Chat screen) either way.
- **System prompt (shared)**: "You are credit-memo-agent, a governed credit-risk analyst. For a renewal memo request: (1) call get_crm_profile, get_credit_exposure, get_transactions, get_compliance_status, get_prior_memo for the case; (2) analyze; (3) draft a memo with Overview (requested amount, utilization, facility type, risk rating, covenant status) and Key Considerations (numbered) plus a Recommended Decision; (4) call workflow__submit_credit_memo with the memo; (5) if approval_required, stop and report the request_id. Never invent data. Use only values returned by the tools."
- Determinism: memo fields must match fixtures; engine validates required fields (amount, utilization %, rating, ≥3 considerations, decision) and **re-prompts once** on missing fields before failing the step (guards LLM non-determinism, §13 R5).
- Sandbox policy: the nemoclaw sandbox runs under its platform policy (video shows `credit-memo-policy`, 3 egress rules, ns `agent-system`). Creating that policy in the Agent Platform UI would be platform-side state — **constraint: loop does not create platform objects**. Instead: M3 gate verifies the existing sandbox policy permits egress to `credit-memo-mcp.slvd.svc`, `litellm-helm.project-user-aieadmin.svc`, engine svc (proven by the real tool-call round-trip in A4/A7). If egress is blocked, this is the single documented escalation (only exception to "no platform changes"), and the `direct_llm` fallback keeps all gates green meanwhile.

### 4.5 `mailpit` (container only, config in chart)
- SMTP :1025, web UI :8025. Sender `noreply@agentplatform.local` (video: `noreply@agentplatform.hpe.com` — domain deviation noted §14).
- **Approval email format (video-identical body)**: title "Agent Platform – Access Request"; fields Request ID / User / Agent (`credit-memo-agent`) / Tool / Host (`credit-memo-mcp/workflow__submit_credit_memo`) / Reason ("Agent requires approval to invoke governed MCP method: workflow__submit_credit_memo"); buttons **Approve (8 h)** / **Approve (24 h)** / **Reject** → signed links; "view in Admin Dashboard" link (→ portal screen 4); "links expire in 24h".
- **Client notification**: subject "Loan Application Approved" after COMPLETED.

### 4.6 `charts/slvd` — Helm chart
- Components (exactly 1 pod each, per standing requirement): `portal` (nginx static, :80), `engine` (:8080), `mcp-server` (:8000), `mailpit` (:1025/:8025).
- `VirtualService` (host `slvd.aie.cs1.ctc.sg.lab`) routing `/` → portal, `/api` → engine, `/mail` → mailpit UI (single external URL for the demo).
- `EzAppConfig` (ns `ui`) with static endpoint, chartVersion from chartmuseum.
- PVC for `/data` (docs + audit); fallback emptyDir if no default StorageClass (loop-verified).
- All workloads: `sidecar.istio.io/inject: false` (avoids the known 503 internal-mTLS issue); secrets via K8s Secret (no values in git; `values-secrets.yaml` gitignored, template provided).
- `helm lint` + `helm template` rendered into CI gate.

---

## 5. Data & API contracts

**Case fixture (Acme, CR-2026-00451)** — canonical JSON (source of truth for memo + tests):
```json
{
  "case_id": "CR-2026-00451", "client": "Acme Industrial Holdings", "client_code": "CL-77821",
  "type": "Renewal Decision Memo", "amount_usd": 5000000,
  "crm": {"industry": "Industrial Manufacturing", "relationship_years": 7, "beneficial_ownership_update": "pending"},
  "credit": {"facility": "Revolving credit", "limit_usd": 5000000, "utilization_usd": 3800000, "utilization_pct": 76, "risk_rating": "BB", "covenant_status": "In compliance with covenants"},
  "transactions": {"delinquencies": 0, "trend": "stable"},
  "compliance": {"kyc_status": "pending", "kyc_detail": "beneficial ownership update required", "sanctions": "clear"},
  "prior_memo": {"conditions": ["Quarterly reporting", "No additional unsecured borrowing"], "open_follow_up": "Collateral valuation update needed"},
  "policy": {"approval_required": true, "reasons": ["amount >= $5M", "KYC pending"]}
}
```
**Event (SSE) schema**: `{run_id, step: 1..10, state: "done|active|pending|failed", ts}`.
**Run record**: `{run_id: "RUN-NNNNN", case_id, status, requested_by, approved_by, approval_role, request_id, memo_path_draft, memo_path_official, started_at, completed_at, steps[]}`.
**Audit entry**: `{ts, actor, action, detail}` (7 canonical entries per §4.1 screen 5).
**Approval decision**: `{request_id, decision: "approve|reject", ttl_hours: 8|24, decided_by, ts, link_hash}` — HMAC signature verified by engine before acting.

---

## 6. Technical requirements & CS1 constraints

| Area | Requirement |
|---|---|
| Images | Built locally (docker 29.1.3), tagged `registry.ctc.sg.lab:5000/slvd/<comp>:<chartver>`; **pre-pull all images via probe pods in ns `slvd` before `helm install`** (CS1 lesson: slow pulls → 45m EzAppConfig timeout → helm lock). Fallback registries: ghcr.io/docker.io (both verified pullable on CS1). Loop verifies registry push access first (R1). |
| LLM | `http://litellm-helm.project-user-aieadmin.svc.cluster.local:4000/v1`, model `qwen3-8-27b-int4-dflash2`, key from `litellm-helm-masterkey` secret (mounted, never in git). **Gate**: before any golden run, verify `/v1/models` 200 + one completion with `max_tokens ≥ 256` returns non-null `content` (reasoning model quirk). Fallback: direct Knative model endpoint (loop discovers via kubectl). Note: litellm EzAppConfig currently shows `warning` — health gate catches it. |
| Istio | VS on `istio-system/ezaf-gateway` (pattern proven by nemoclaw/airflow/kubeflow VSes). External-only access via VS; internal service calls plain HTTP, sidecar-inject disabled. |
| Storage | PVC `slvd-data` using **default StorageClass `nfs-csi`** (verified present; `rook-ceph-block` as alternative); loop verifies binding at deploy; fallback emptyDir (demo-scoped, documented). |
| Namespaces | New ns `slvd` for slvd chart; `nemoclaw` ns only touched via its own chart ConfigMap patch (MCP registration). **Loop guard: all kubectl write ops must target {slvd, ui, nemoclaw-configmap-only} — enforced by `orchestrate/gates.py` namespace allowlist.** |
| Secrets | litellm key, JWT/HMAC secrets, mailpit none → K8s Secrets generated at deploy (`helm secret`-style base64 in `values-secrets.yaml`, gitignored). Secret-scan gate (§10 A8) fails the loop if any key lands in git. |
| Versioning | Chart `slvd` versioned semver; **bump per iteration** (standing requirement); commit per loop iteration (semantic: `feat:/fix:/test:/chore:`). |
| Pod budget | Exactly 1 pod per component (portal/engine/mcp/mailpit = 4 pods + existing nemoclaw 2). Loop asserts `kubectl get pods -n slvd | wc -l == 4` and no extra deployments. |
| Performance | Step latency budget: each data step < 5s (mock), memo draft < 90s (LLM, timeout 120s), full happy path < 4 min. SSE reconnect with `Last-Event-ID`. |
| Observability | Structured JSON logs (stdout); `/healthz` per component; engine `/api/runs` list for dashboard; e2e collects `kubectl logs` into `logs/iter-<N>/` for defect triage. |
| Compatibility | Python 3.11 venv per component dir; Node 20+ for portal build; pinned `requirements.txt` per component; `package.json` pinned for portal. |

---

## 7. Non-functional requirements

1. **Security**: JWT auth on all portal→engine calls; token-scoped data access in MCP (analyst can only see allowed cases); HMAC-signed single-use approval links with 24h expiry; no secrets in repo; no plaintext keys in logs; audit log immutable; approval decision recorded before workflow resumes (no TOCTOU).
2. **Auditability**: every state transition, tool call, and decision timestamped UTC ISO-8601; Run Summary screen matches audit 1:1.
3. **Idempotency**: re-POSTing an approval decision returns the recorded decision; re-starting a run for the same case while active is rejected (409); resubmit after rejection is allowed (video's "Re-submit (Approved)" path).
4. **Resilience**: agent timeout (120s) → step FAILED + auto-retry ×3 → run FAILED (loop treats as defect); engine restart mid-run → run recovered from SQLite (state persisted); mailpit down → approval still possible via Admin dashboard link (email is convenience, decision API is authoritative).
5. **Determinism for testing**: fixtures + seeded RNG + `SLVD_LLM=0` stub → e2e fully deterministic without a GPU/LLM.
6. **Reproducibility**: one `make deploy` reproduces the entire CS1 state from git (chart + values + pre-pull + VS + EzAppConfig); `make clean` removes everything (BYOA teardown procedure).

---

## 8. Helm & deployment design (CS1)

1. `make build` → docker images → push `registry.ctc.sg.lab:5000/slvd/<comp>:<chartver>` → `helm package charts/slvd` → push to chartmuseum **via `kubectl port-forward -n ez-chartmuseum-ns svc/chartmuseum 18080:8080`** (chartmuseum is ClusterIP-only, no VS — verified; loop keeps the port-forward alive, restarts on drop; `helm push http://127.0.0.1:18080`).
2. `make prepull` → probe pod per image in ns `slvd` (parallel, 5-min timeout each).
3. `make deploy` → `helm install slvd ./slvd-<ver>.tgz -n slvd` (namespace created by chart) → wait for 4/4 ready (10-min timeout).
4. **External URL verification** (browser-reachable, no internal bypass — standing rule): `curl -sk https://slvd.aie.cs1.ctc.sg.lab/healthz` → 200; portal page 200 with title "Credit Risk Portal".
5. **Agent verification** (nemoclaw): dashboard via `https://nemoclaw.aie.cs1.ctc.sg.lab/?token=*** 200 + "OpenClaw Control"; LLM completion non-null (max_tokens ≥ 256); if WebSocket fails `device identity required` → add ingress proxy IP to `gateway.trustedProxies` ConfigMap (known fix).
6. nemoclaw ConfigMap patch (MCP registration) → rolling restart of nemoclaw pod (1 replica, expected).
7. **Soak**: 10-min stability watch (no restarts, no error logs) — pass = stable.
8. Teardown (for re-iterations): `helm uninstall slvd -n slvd` → delete EzAppConfig → **verify no orphan pods** → delete ns `slvd` (BYOA procedure; the loop does this only between chart-version iterations, never mid-run).

---

## 9. Testing strategy

### 9.1 Unit (per component, pytest + vitest)
- **Policy engine**: full 4-way matrix {amount ≥5M × KYC pending} + boundary ($4,999,999 / $5,000,000) — 12 cases.
- **FSM**: all legal transitions + 8 illegal-transition rejections; crash-recovery (persist → reload → resume).
- **Auth**: JWT valid/expired/tampered; HMAC link valid/expired(24h)/double-use/single-use.
- **MCP governance**: token with/without case access → 200/403; tool-call webhook emitted per call.
- **Memo validator**: field completeness check (amount, utilization%, rating, ≥3 considerations, decision) with 5 mutation cases.
- **Audit**: append-only enforcement (UPDATE blocked), UTC timestamp format.
- Portal: vitest component tests for the 5 screens (step-state rendering, memo field rendering, button enable/disable logic).

### 9.2 Integration (docker-compose, local, stub agent — no LLM)
Full stack: portal + engine + mcp + mailpit + **stub-agent** (deterministic: calls all 5 tools in order, returns templated memo, calls submit). Run all scenarios (§9.4) with `SLVD_LLM=0, SLVD_SIMULATION=1` (auto-approve) plus one manual-approve variant (curl the signed link).

### 9.3 LLM golden run (optional local / required cluster)
Real agent + litellm: assert memo contains all canonical fields (regex/JSON check against fixture), non-null content, finish_reason stop, `max_tokens ≥ 256` honored. Retries: 2 (LLM flakiness budget).

### 9.4 Simulation scenarios (the e2e matrix — all must pass)
| # | Scenario | Inputs | Expected |
|---|----------|--------|----------|
| S1 | Happy path (video) | CR-2026-00451, $5M | 10 steps → AWAITING_APPROVAL → email w/ correct fields → approve(8h) → COMPLETED, RUN-NNNNN, draft→official paths, 7 audit entries, client "Loan Application Approved" mail, Run Summary matches §4.1-5 |
| S2 | Below threshold | CR-2026-00452, $2M, KYC clear | No approval email; run auto-completes at Submission; audit has "Policy evaluated — no approval required" |
| S3 | KYC pending below threshold | CR-2026-00453, $2M, KYC pending | Approval triggered (policy OR-rule); same flow as S1 |
| S4 | Reject path | CR-2026-00451 → decision=reject | Run REJECTED; audit "Rejected by Sarah Chen (Senior Credit Officer)"; NO official publish; resubmit allowed → new request UUID → approve → COMPLETED |
| S5 | Identity failure | Bogus JWT / token w/o case access | 401/403; run not started; audit "Identity validation failed" |
| S6 | Link expiry/tamper | Tampered HMAC / expired link | 403; decision not recorded; run stays AWAITING_APPROVAL |
| S7 | Agent failure | Stub-agent killed mid-run | Step FAILED after 3 retries → run FAILED; portal shows failed state; no silent hang |
| S8 | Resubmit after approval | Re-submit after COMPLETED | 409 (idempotent guard) |

### 9.5 Cluster e2e (CS1, simulation mode then golden)
`e2e/cluster_e2e.sh`: deploy → URL checks (§8.4–8.5) → S1 via real UI API (curl sequence emulating clicks: login → start run → SSE watch → auto-approve) → assertions on memo file (kubectl cp from PVC), audit API, mailpit API (`GET /api/v1/messages` shows access-request + approved mails), Run Summary parity → S4 reject → soak 10 min. **Then golden**: `SLVD_SIMULATION=0, SLVD_LLM=1` full human-loop simulation (auto-click the signed link after 10s) with real LLM memo.

### 9.6 Defect-free gate (acceptance, §10)
A run is "green" only when: all unit + integration + all 8 scenarios + cluster e2e + golden run + soak + security scan pass, AND `defects.jsonl` has zero open P0/P1. Any red → loop auto-fix cycle (§11).

---

## 10. Acceptance criteria (the defect-free definition)

| ID | Criterion | Verified by |
|---|-----------|-------------|
| A1 | Unit tests 100% pass (≥ 60 cases incl. policy matrix, FSM, auth) | `make test-unit` |
| A2 | All 8 simulation scenarios pass locally (compose, stub agent) | `make test-e2e` |
| A3 | CS1: 4/4 slvd pods ready; portal 200 at `https://slvd.aie.cs1.ctc.sg.lab` (external, browser-reachable); engine healthz 200 | `e2e/cluster_e2e.sh` step 1 |
| A4 | CS1: nemoclaw agent healthy — dashboard 200, LLM completion non-null (max_tokens ≥ 256) | `e2e/cluster_e2e.sh` step 2 |
| A5 | Cluster S1 (sim): 10 steps complete, memo at `/data/docs/official/credit/2026/CR-2026-00451/memo.md` with all canonical fields, 7 audit entries timestamped, mailpit has access-request + "Loan Application Approved", Run Summary parity | `e2e/cluster_e2e.sh` step 3 |
| A6 | Cluster S4 (sim): reject → REJECTED, no official publish, resubmit → COMPLETED | `e2e/cluster_e2e.sh` step 4 |
| A7 | Golden run (real LLM, real email link auto-clicked): memo fields pass, decision timestamped, run COMPLETED | `e2e/golden_run.sh` |
| A8 | Security: `gitleaks` clean on repo; no secret literals in rendered chart; HMAC/JWT tests green; audit immutability green | `make test-security` |
| A9 | Soak: 10 min, zero pod restarts, zero ERROR-level log lines | `e2e/soak.sh` |
| A10 | Pod parity: exactly 4 slvd pods + 1 nemoclaw; no orphan deployments | `kubectl` assert |
| A11 | Video parity: 7-frame visual checklist (screens match §4.1 content verbatim: labels, IDs, amounts, copy) — checked by scripted DOM assertions (playwright headless) against the deployed portal | `e2e/visual_parity.py` |
| A12 | Reproducibility: `make clean && make deploy` from clean git state succeeds end-to-end | loop final iteration |

**P0/P1 definition**: P0 = any A-item failure; P1 = any scenario failure or security finding; P2 = cosmetic (fix opportunistically).

---

## 11. Autonomous development loop (self-driven, no manual intervention)

### 11.1 Topology
- **Supervisor**: `orchestrate/loop.py` (Python, stdlib + subprocess) — single instance (flock), runs phases, records state, decides pass/fix/stop.
- **Workers**: one-shot `hermes chat -q "..."` invocations (profile `slvd-dev`, `--yolo` equivalent via `approvals.mode: off` in that profile's config, terminal backend local, cwd = project) for: **implement** (build missing pieces), **review** (LLM code review with structured JSON defect output), **fix** (apply fixes for a defect batch), **diagnose** (parse test failures + k8s logs → root-cause patch).
- **State**: `orchestrate/state.json` (iteration, phase, gate results), `defects.jsonl` (append-only, severity/file/desc/status), `iteration_log.md` (human-readable), `logs/iter-<N>/`.
- **No human in the loop**: the loop never asks. The only human-visible artifacts are git history, logs, and the final `HANDOFF.md`.

### 11.2 Iteration protocol (one cycle)
```
1 BUILD      make build (images, helm package, chartmuseum push)        [gate: exit 0]
2 TEST-UNIT  make test-unit                                              [gate: all green]
3 REVIEW     hermes-worker "review diff since last iteration → JSON defects" + static gates (ruff, tsc, helm lint/template, gitleaks)
             → defects P0/P1 queued; P2 noted
4 FIX        if defects: hermes-worker "fix these defects (context: files, repro, logs)" → git commit "fix: <batch>"
5 TEST-E2E   make test-e2e (compose, stub agent, 8 scenarios)            [gate: all green]
6 DEPLOY     make prepull && make deploy (CS1)                           [gate: 4/4 ready, VS 200]
7 CLUSTER    e2e/cluster_e2e.sh (A3,A5,A6,A10) + e2e/soak.sh (A9)        [gate: all green]
8 GOLDEN     e2e/golden_run.sh (A7) — only after 7 green                 [gate: pass]
9 FINAL      e2e/visual_parity.py (A11) + make test-security (A8) + repro check (A12, every 3rd iter)
             → ALL GREEN ⇒ ACCEPTANCE PASS ⇒ stop loop, write HANDOFF.md
             → any red ⇒ append defects, iterate (cap: 40 iterations / 24h wall)
```
- Phases are **idempotent and resumable** (state.json tracks last-green phase; on supervisor restart, resume from there).
- **Cluster-down handling**: if kubectl unreachable >10 min → skip phases 6–9, keep cycling 1–5 (local work continues), retry cluster every 10 min; never block the local loop on cluster infra (known CS1 failure mode: webhook/quota outages are infra, not our config).
- **Helm-lock handling** (known CS1 trap): on `helm install/upgrade` timeout → delete our EzAppConfig → verify no orphan pods (allowed ns only) → pre-pull → retry with backoff (×3).
- **LLM flakiness**: golden run retries ×2 before failing the gate.
- **Stall dead-man**: any phase > 45 min → kill worker, mark phase FAILED, re-enter at that phase (prevents infinite hang).
- **Cost/budget**: per-iteration wall cap 45 min; total cap 24 h / 40 iterations → on exhaustion: stop, write `STALLED.md` with exact state + next action (the only human-touch point, and only if the machine genuinely can't finish).

### 11.3 Review worker contract (structured output)
Worker must emit JSON: `{"defects":[{"severity":"P0|P1|P2","file":"...","line":N,"desc":"...","repro":"...","fix_hint":"..."}]}`. Non-JSON output = review FAILED → re-run once, then treat as pass-with-P2 (log it). Review prompt includes: the diff, the acceptance criteria §10, and the CS1 constraint list §6.

### 11.4 Start / monitor / stop (exact commands)
```bash
cd ~/projects/secure_loan_verification_demo
source venv/bin/activate
python3 orchestrate/loop.py start          # starts supervised loop (nohup'd, flock-guarded)
tail -f orchestrate/iteration_log.md       # watch progress
python3 orchestrate/loop.py status         # current phase, last gate results, open defects
python3 orchestrate/loop.py stop           # graceful stop (finishes current phase)
python3 orchestrate/loop.py resume         # resume after supervisor crash
cat orchestrate/state.json defects.jsonl   # machine state
# Final: HANDOFF.md (acceptance report + how to run the demo) — loop writes it on PASS
```
The loop is designed to be launched from this session via `terminal(background=true, notify=true)` and to survive session close (nohup + state file; per user requirement: long jobs survive session close).

### 11.5 Guardrails (why "no manual intervention" is safe)
- **Blast radius**: kubectl write allowlist `{slvd, ui: EzAppConfig only, nemoclaw: openclaw ConfigMap only}` enforced in `gates.py`; any out-of-scope kubectl command is rejected by the worker wrapper.
- **Secrets**: `values-secrets.yaml` generated locally at deploy, gitignored; gitleaks gate kills the loop if a secret is ever committed.
- **Destructive ops**: `make clean` only targets ns `slvd` + our EzAppConfig; never touches other releases.
- **Yolo scope**: `approvals.mode: off` only in the `slvd-dev` profile (isolated), not the default profile.

---

## 12. Milestones

| M | Scope | Exit criterion |
|---|-------|----------------|
| M0 | Repo skeleton, venvs, Makefile, docker-compose, stub agent, mock data, charts stub | `make test-e2e` S1 green locally with stubs (smoke) |
| M1 | Real components: portal (5 screens), engine (FSM+API+SSE+audit+docs), mcp-server (6 tools), mailpit | A1, A2 green (all scenarios, stub agent) |
| M2 | Agent wiring: nemoclaw openclaw.json MCP registration + system prompt + memo validator | Local golden (via kubectl port-forward to litellm) memo passes field checks |
| M3 | Chart + CS1 deploy: images pushed, pre-pull, helm, VS, EzAppConfig, pod parity | A3, A4, A10 green |
| M4 | Cluster e2e sim + golden + soak + visual parity + security scan | A5–A9, A11 green |
| M5 | Acceptance: full gate green 2 consecutive iterations, `make clean && make deploy` repro, HANDOFF.md | **All of §10 green; loop stops on PASS** |

---

## 13. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| R1 | Image push to `registry.ctc.sg.lab:5000` denied | M | H | Loop first-iteration probe: `docker push` dry-run; fallback ghcr.io/docker.io base images (both pullable on CS1) |
| R2 | litellm unhealthy (EzAppConfig shows `warning`) | M | H | Health gate before golden (A4); fallback direct Knative model endpoint (loop discovers via kubectl); second fallback: local stub (`SLVD_LLM=0`) to keep other gates progressing |
| R3 | Slow image pulls → EzAppConfig 45m timeout → helm lock | H | M | Pre-pull probe pods before install; delete EzAppConfig + verify orphans before retry (proven CS1 playbook) |
| R4 | Istio sidecar breaks internal calls (503 pattern) | M | M | `sidecar.istio.io/inject: false` on all slvd workloads; VS for external only |
| R5 | LLM memo non-deterministic / missing fields | H | M | Deterministic system prompt + required-field validator + 1 re-prompt + 2 golden retries; S1-sim uses stub so gate is not LLM-dependent |
| R6 | OpenClaw MCP client transport unsupported/quirky | M | M | REST mirror on mcp-server; agent system prompt allows HTTP fallback; M2 exit verifies real tool-call round-trip before M3 |
| R7 | PVC/default StorageClass issues on CS1 | M | M | Loop checks StorageClass; fallback emptyDir (demo-scoped) with note |
| R8 | nemoclaw ConfigMap patch breaks existing release | L | M | Patch is additive (mcp section only); before/after dashboard 200 check in A4; rollback = re-apply prior ConfigMap (kept in git) |
| R9 | Device-identity WebSocket failure on nemoclaw dashboard | M | M | Known fix: `trustedProxies` + `?token=` URL (baked into deploy script) |
| R10 | Cluster infra outage (webhooks/quota) mid-loop | M | H | Loop skips cluster phases, keeps local loop alive, retries (known CS1 failure mode: infra ≠ our config) |
| R11 | Loop burns budget without convergence | M | M | 40-iter/24h caps; per-phase stall kill; `STALLED.md` handoff |
| R12 | Golden run needs "Sarah" approval — loop must not wait for a human | — | H | Simulation auto-approve (S1) is the gate; golden uses signed-link auto-click (curl) after 10s — fully unattended |
| R13 | Memo "decision" (recommended approve/reject) is LLM-generated — could contradict policy | M | M | Decision field validated against fixture expectations (Acme → "approve with conditions"); mismatch → re-prompt |
| R14 | Chartmuseum port-forward drops mid-push | M | M | Health-checked backgrounded port-forward (auto-restart); resumable push; retry ×3 before failing phase |
| R15 | NFS PVC fails to bind in ns `slvd` (RBAC/quota) | L | M | emptyDir fallback (demo-scoped); documented in HANDOFF; loop switches storageClass to `rook-ceph-block` first |
| R16 | Loop's own LLM (worker model) unavailable | L | H | Worker model = litellm CS1 endpoint (same key, proven alive) with workstation provider fallback; per-iteration health probe; if both down → phase marked LLM_UNAVAILABLE, retry — never commit code without an LLM review pass |

---

## 14. Deliberate deviations from the video (documented, acceptable)

1. **"Agent Platform" PCAI console screens** (Providers/Policies tabs shown mid-video) are platform product UI, not app code — not replicated; equivalent governance is real (MCP gating + policy engine + sandbox policy values) and visible via portal Run Summary/Audit.
2. **Phone push "Loan Application Approved"** → delivered as client **email** (mailpit) + portal status banner. (No mobile push infra in scope.)
3. **Mail sender domain** `agentplatform.hpe.com` → `agentplatform.local` (demo domain).
4. **Login**: video shows pre-authenticated analyst; replica has a simple password login (demo creds documented) to exercise the identity→JWT→MCP-scoping chain that the video implies ("data I'm allowed to see").
5. **Mailpit** is dev webmail; production equivalent is an SMTP relay (swap is a chart value).
6. **Case/Run IDs**: video's `RUN-90027` / UUID `ac354da7-…` are regenerated per real run (format parity, not value parity).
7. **Header email**: video shows the demo operator's email (prakash.mirji@gmail.com) as the PCAI session; replica shows the logged-in analyst's identity (Nick Johnson) — the Analyst Portal card carries the video's session-info values verbatim.

---

## 15. Rollout & verification procedure (final, post-loop)

1. `python3 orchestrate/loop.py status` → confirm ACCEPTANCE PASS + HANDOFF.md.
2. `make demo-run` (fresh cluster run, real LLM, human clicks the email link in Mailpit UI) → operator walkthrough: login → generate → watch 10 steps → open Mailpit → approve(8h) → watch resume → Run Summary + Audit → open published memo → client email "Loan Application Approved".
3. Screenshots of the 7 video-parity frames saved to `docs/parity/` for the record.
4. `git push` final state; chart `slvd-<final>` in chartmuseum; EzAppConfig ready/ok.
5. Cleanup option: `make clean` (BYOA teardown) if the demo is done.

---

## 16. Gap review of this plan (performed 2026-09-12, post-draft)

Method: re-read the plan against (a) the video/SRT evidence, (b) live CS1 state re-verified today, (c) the standing user constraints, (d) failure-mode analysis of the autonomous loop itself. Findings F1–F12; each marked **FIXED** (patched into the plan above) or **ACCEPTED** (documented residual).

### F1 — Agent egress policy could not be satisfied without platform changes → **FIXED**
Original plan claimed the slvd chart "sets `SLVD_SANDBOX_POLICY=credit-memo-policy`" — false: sandbox policies are platform-side Agent Platform objects, and the constraint is "only modify our charts". **Resolution**: two agent backends (§4.4) — `direct_llm` (engine runs the agent loop over litellm + MCP REST mirror) is the default path with zero platform dependency; `openclaw` is the video-faithful path enabled at M2 only if the live sandbox policy permits egress to the slvd services (proven by a real round-trip). Single documented escalation if egress is blocked.

### F2 — Chartmuseum is ClusterIP-only; "helm push" was not possible as written → **FIXED**
Verified: no VS/ingress for chartmuseum (ClusterIP 172.30.159.160:8080). **Resolution**: loop runs a backgrounded `kubectl port-forward` to 127.0.0.1:18080, health-checked and self-restarting (§8.1). New risk R14 (port-forward drops mid-push → resumable push, retry ×3).

### F3 — StorageClass assumption unverified → **FIXED (verified)**
Live check: default SC = `nfs-csi` (NFS CSI), `rook-ceph-block` also present. Plan now names `nfs-csi` explicitly; binding verified at deploy with emptyDir fallback.

### F4 — Video-parity contradictions found between frames and SRT → **FIXED**
- *Amount*: frame shows Amount pre-filled; SRT says the analyst "enters the loan requested amount… $5 million". Original plan had a read-only field → **changed to editable, pre-filled** (S1 test drives the policy threshold through it).
- *Re-submit button*: frame shows it green/active **while still awaiting approval** (SRT: "you can re-submit manually after approval" refers to post-approval re-submission). Original plan said "enabled when decision recorded" — **reworded** (§4.1 screen 4) to match the video: visible+enabled while awaiting (re-check), force-resume after decision.
- *Memo "Recommended Decision"*: SRT says the memo includes "a recommended decision", but the frame's memo body shows Overview + Key Considerations only (the decision section was likely below the captured viewport). **Added** "plus a Recommended Decision" to the system prompt and memo validator (required field).
- *Case-ID format*: form shows `CR-2026-00451`, memo header shows `CL-77821` — both kept (case ID vs client code), now explicit in the fixture.

### F5 — The autonomous loop itself depends on an LLM; its availability was unaddressed → **FIXED**
If the workstation LLM provider (the loop's worker model) is down, the loop stalls. **Resolution**: R16 added — worker model = the same litellm CS1 endpoint (proven alive, same key), with the workstation provider as fallback; `loop.py` probes model health at start and per-iteration; if both are down, the loop degrades to deterministic-only phases (build/test/fix-by-heuristic is NOT allowed — it marks the phase `LLM_UNAVAILABLE` and retries, so no unreviewed code is ever committed without an LLM review pass).

### F6 — "No manual intervention" vs. helm-lock recovery deletes the EzAppConfig → **FIXED**
Deleting the EzAppConfig is allowed (it's our object), but the plan must guarantee it never cascades to other releases. **Resolution**: gate in `gates.py` — EzAppConfig deletion only for `name` matching our release (`slvd*`), with pre/post orphan-pod verification scoped to ns `slvd` only.

### F7 — Idempotency gap: "run for same case while active rejected (409)" vs. the video's repeated access-request emails (multiple prior requests to Sarah) → **ACCEPTED + clarified**
The video shows stale prior requests (different run attempts). Plan keeps 409 for *same active run*; a **new** run for the same case after completion/rejection is allowed (S4 resubmit). Stale approval requests auto-expire (24h) and are listed read-only. No behavior change needed — documented to prevent the loop "fixing" working behavior.

### F8 — Mailpit in-cluster reachability for the loop's auto-approval (golden run) → **FIXED**
The golden run must click Sarah's link unattended. **Resolution**: loop reads the approval email via Mailpit's HTTP API (`GET /api/v1/messages`, parse signed link from body) instead of screen-scraping the webmail UI; the link then hits the VS (`/api/approvals/…`). Also covers R12 explicitly.

### F9 — Pod parity check vs. istio-proxy sidecars → **FIXED**
`kubectl get pods | wc -l` counts only *pods* (sidecars are containers), so 4 slvd pods + 1 nemoclaw pod is the correct assertion — but the plan originally implied "5 pods total" for our app; **corrected**: 4 slvd pods (portal/engine/mcp/mailpit), each 1 replica; nemoclaw stays 1 pod (2 containers). A10 asserts deployments=4 in ns slvd and restart count 0.

### F10 — "Browser-reachable" verification uses only curl → **FIXED**
Standing rule: external URL must work from a real browser. **Resolution**: A3/A11 use headless Chromium (playwright) from the workstation against the external URL (not kubectl port-forward), including one full S1 click-through in the golden run; curl checks remain as fast gates.

### F11 — LLM memo timing vs. step budget → **FIXED**
Reasoning model (qwen3-8-27b-int4-dflash2) can take 60–120s for a full memo with function-calling over 5 tools. Original 90s memo budget was tight. **Resolution**: per-LLM-call timeout 180s; memo step budget 300s; full happy-path budget 6 min (simulation path < 1 min). SSE keeps the portal responsive regardless.

### F12 — No definition of "defect-free" for LLM-generated memo *wording* → **FIXED**
Acceptance checks **structure + canonical values** (fields, numbers, rating, consideration topics via keyword assertions), not exact prose — wording is LLM-variable. Exact-prose parity would make the gate flaky. Documented in A5/A7 wording.

### Residual (accepted, monitored)
- **litellm EzAppConfig status `warning`** (pre-existing, not ours): health gate A4 treats "our LLM calls work" as the criterion; if litellm degrades, fallback chain = direct Knative endpoint → `SLVD_LLM=0` (other gates keep progressing). Escalate to user only if both fail for >24h (the loop's only allowed human-touch, per §11.2).
- **Node v26 + Vite**: minor version risk; build is a fast gate, fix = pin vite version (loop handles).
- **NFS CSI RBAC for ns `slvd`**: if the PVC fails to bind, emptyDir fallback keeps the demo working (docs/audit non-persistent — acceptable for a demo; noted in HANDOFF).

**Review verdict**: plan v1 had 12 material gaps; 10 fixed by patch, 2 accepted-and-documented with mitigations. No gap affects the acceptance definition itself. Plan approved-for-execution (v1.1).
