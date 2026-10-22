# AI Goals (Phase 2 + Phase 3A)

AI Goals lets an authenticated operator describe **what** should happen to one
Proxmox guest or one Kubernetes Deployment, supply a small set of variables,
preview a server-built plan, and send it to a human approver. The AI never
executes anything. With `GOALS_EXECUTE_ENABLED=true` a second explicit click
dispatches the approved plan to the healer loopback control API; the healer
re-validates everything and is the only actor that touches a target.

> **Phase 2 scope:** plan, preview, approval, rejection, cancellation, audit,
> opt-in execution through the healer HMAC control API, journal-backed replay
> protection, and read-only reconcile. Execution remains off by default and
> `DRY_RUN=1` remains the healer default.
>
> **Phase 3A scope:** Kubernetes Deployment-only `rollout_undo`, restricted to
> the healer's `K8S_ALLOW` list. Multi-step plans, other k8s actions, and HA are
> not part of this phase.

## Trust boundary

```text
operator
  │  goal text + variables (untrusted data, never commands)
  ▼
Laya Ops UI ── session + exact Origin + CSRF ──► Ops API
                                                   │
                          server resolves target from healer state
                          (guest) or the k8s allow-list (Deployment)
                          rules planner validates; optional LLM only advises
                                                   │
                          immutable plan + sha256 plan hash in SQLite
                                                   │
                          human approver + one-time code (+ passphrase)
                                                   │
                                                approved
                                                   │
                                    second explicit Execute click
                                                   │
                          HMAC-signed POST → healer 127.0.0.1:9182
                                                   │
                          healer re-validates signature, TTL, PROTECT,
                          state, cooldown, rate limit, EXEC_LOCK
                                                   │
                                   journal claim (claimed → done|failed)
                                                   │
                          qm|pct start|resume|reset  ·  rollout_undo
                                                   │
                          Ops follows GET /runs/{plan_id}; no auto-retry
```

Hard rules:

- **AI proposes, server validates, human approves, healer executes.**
- The Proxmox planner may only choose from `start`, `resume`, `reset`, `noop`,
  `escalate`; the Kubernetes planner only from `rollout_undo`, `noop`,
  `escalate`. `noop` and `escalate` are not executable.
- The target is resolved server-side: a guest comes from `/api/state`, a
  Deployment from the healer's `/api/k8s` allow-list. Neither the browser nor
  the model may supply or change vmid, node, namespace, deployment, or revision.
- `PROTECT` is absolute for guests; `K8S_PROTECT` is absolute for Deployments
  and wins over `K8S_ALLOW`. A protected target produces a `blocked` preview and
  cannot be created. The healer re-checks both before every execution.
- No shell, SSH, kubectl, URL, PromQL, or free-form command is accepted as a
  goal or variable.
- `DRY_RUN=1` remains the healer default. With dry-run on, the healer records
  the run, returns `dry_run=true`, and does not change the target.

## Lifecycle

```text
pending_approval ──approve──► approved ──execute──► dispatching ──► executing
       │                         │                                   │
       ├──reject──► rejected     ├──cancel──► cancelled               ├─► succeeded
       ├──cancel──► cancelled    └──expire──► expired                 ├─► failed
       └──expire──► expired                                          └─► unknown
```

With `GOALS_EXECUTE_ENABLED=false` the lifecycle stops at `approved`
(`execute` returns `409 execution_disabled`).

- `dispatching` means Ops has atomically claimed the execution and is sending
  the signed request.
- `executing` means the healer accepted the plan (`202`) and Ops is following
  the journal.
- `succeeded` / `failed` are terminal outcomes reported by the healer.
- `unknown` means the outcome cannot be proven from Ops (timeout, transport
  error, 5xx, stale lease, healer restart). Ops never retries automatically.
  An approver may `reconcile`, which only performs a signed `GET /runs/{plan_id}`.

A preview may be `ready` or `blocked`. `needs_input` is reserved by the response
type but is not returned by the current templates; required variables are
enforced by request validation instead (`422 invalid_request`). Blocked reasons:

| reason | kind | meaning |
| --- | --- | --- |
| `protected_target` | both | the guest is in `PROTECT`, or the Deployment is in `K8S_PROTECT` |
| `target_metadata_missing` | guest | state has no usable `node`/`jenis` for this guest |
| `no_safe_action` | both | observed state has no executable safe action (only `noop`/`escalate`) |

A preview request can also fail before a plan exists:

| status | detail | meaning |
| --- | --- | --- |
| `404` | `target_not_found` | the guest is missing from `/api/state` |
| `404` | `target_not_allowed` | the Deployment is not in `K8S_ALLOW` (or is outside `K8S_GOAL_NS`) |
| `503` | `k8s_unavailable` | the healer `/api/k8s` snapshot could not be read |
| `503` | `healer_state_unavailable` | guest state could not be read |
| `503` | `healer_knobs_unavailable` | `PROTECT` could not be verified, so nothing is offered |

`GET /api/goals/targets?template_id=` returns the picker rows for the template's
`target_kind`. For a guest template each row is
`{vmid, name, node, guest_type, status, auto, protected}`. For a k8s template
each row is `{namespace, deployment, revision, previous_revision, status,
replicas, available, images, previous_images, ok, allowed, protected}` taken
from the healer's `/api/k8s`. When the snapshot itself is unavailable the
response carries `error` (`k8s_unavailable` or `k8s_disabled`) and no rows.

## Templates and variables

Templates are code-defined in `backend/app/goals/templates.py`; there is no UI
or database editor for them. Each one declares a `target_kind` and the target
payload the create request must carry.

### `guest.recover.v1` (`target_kind=guest`, target `{vmid}`)

Recover one Proxmox VM/CT. Actions: `start`, `resume`, `reset`, `noop`,
`escalate`.

| variable | required | notes |
| --- | --- | --- |
| `reason` | yes | max 200 chars, shown to the approver |
| `expected_effect` | yes | `running` (default) or `reachable` |
| `allow_reset` | no | default `false`; required before a reset is considered |
| `goal` | no | free-form operator text, max `GOALS_MAX_GOAL_CHARS` (default 1000) |

The goal text is untrusted data for the optional LLM planner. It is stored in
the plan and goals database, so **do not paste credentials or secrets into it**.

Rules for choosing an action:

- `stopped` → `start` (VM or CT)
- `paused`/`suspended` → `resume` (a suspended CT may also be started)
- `running` with a healthy/no-op situation → `noop` (not executable)
- `running` VM, agent not answering, `allow_reset=true` → `reset`
- CT never gets `reset`
- anything else → `escalate` (not executable)

If the target is not in `AUTO_IDS`, the plan is high-risk and carries a warning.
The healer additionally requires `GOALS_ALLOW_NON_AUTO=1` before it will execute
such a plan; without it the healer returns `403 non_auto_forbidden`.

### `k8s.deployment.rollback.v1` (`target_kind=k8s_deployment`, target `{namespace, deployment}`)

Roll one Deployment back to its previous ReplicaSet with `rollout_undo`.
Actions: `rollout_undo`, `noop`, `escalate`.

| variable | required | notes |
| --- | --- | --- |
| `reason` | yes | max 200 chars, shown to the approver |
| `expected_effect` | yes | must be `available` (the only value) |

Rules (Phase 3A is rules-only; the LLM never sees a k8s target):

- `status=degraded` with `previous_revision > 0` and different from the current
  `revision` → `rollout_undo` (always high-risk)
- `status=degraded` without a usable previous revision → `escalate`
- `status=scaled-to-zero` → `escalate` (a deliberately scaled-down Deployment is
  never rolled back)
- `status=available` → `noop`
- anything else → `escalate`

The target must be present in `K8S_ALLOW` and absent from `K8S_PROTECT`, and its
namespace must satisfy `K8S_GOAL_NS` when that is set. Unlike a guest, a
Deployment has no `AUTO_IDS` concept: `rollout_undo` is always high-risk and the
healer does not apply `GOALS_ALLOW_NON_AUTO` or `COOLDOWN` to it.

## Immutable plan and hash

The server builds the complete plan. `plan_hash` is
`sha256(canonical_json(plan))` with sorted keys and compact separators. The plan
JSON is written once; the store's update allow-list cannot modify plan fields.
Approval binds the hash supplied by the approver to the stored hash.

A create request must present the preview's `preview_id`, exact `plan_hash`, and
a caller-generated `idempotency_key` (8–128 chars, unique per requester). Before
creating the goal, the server re-fetches the target and rejects with
`409 state_changed` if the observed state changed since preview:

- guest: `vmid`, `node`, guest type, status, agent liveness, or `PROTECT`;
- Deployment: `namespace`, `deployment`, `revision`, `previous_revision`,
  status, `replicas == 0`, `K8S_ALLOW` membership, or `K8S_PROTECT`. A removed
  allow-list entry is `409 target_not_allowed`; protection is
  `409 protected_target`.

Preview is single-use.

## Approval policy

An identity is an approver only when all of the following hold server-side:

- `GOALS_ENABLED=true`
- `AUTH_MODE` is `password` or `oidc` (never `off`)
- `GOALS_APPROVERS` and/or `GOALS_APPROVER_GROUPS` is configured
- in password mode, `GOALS_ALLOW_PASSWORD_APPROVAL=true`

Names match the OIDC `preferred_username` (or password identity `operator`);
groups are matched against the OIDC `groups` claim. Group claims must actually be
present in the userinfo — configure a Keycloak group-membership mapper if they
are missing.

Self-approval is denied by default (`GOALS_ALLOW_SELF_APPROVAL=false`). Use OIDC
with a separate approver for real two-person control. Password mode has exactly
one identity (`operator`), so it is inherently single-person; to make it work at
all it needs:

```dotenv
GOALS_APPROVERS=operator
GOALS_ALLOW_PASSWORD_APPROVAL=true
GOALS_ALLOW_SELF_APPROVAL=true
```

The UI shows a **single-person approval** warning in that configuration.

Approval requires:

1. approver role, checked server-side;
2. the goal is still `pending_approval` and not expired;
3. the supplied `plan_hash` matches;
4. `confirm=true`;
5. the correct one-time approval code;
6. for high-risk plans, either `GOALS_HIGH_RISK_PASSPHRASE` (if configured) or
   the typed phrase from `requirements.typed_confirmation`.

A plan is high-risk when the action is `reset`, when a guest target is not in
`AUTO_IDS`, or when the action is `rollout_undo` (always). The typed phrase is
`SETUJU <action> <vmid>` for guests and
`SETUJU rollout_undo <namespace>/<deployment>` for Deployments. The code is 12
characters from an unambiguous alphabet, stored only as a salted
PBKDF2-HMAC-SHA256 hash (210,000 iterations), and is cleared when the goal is
approved, rejected, or cancelled. It is returned in plaintext **once**, in the
create response; it cannot be recovered later. Maximum 5 failed code attempts
per 15 minutes, after which approval returns `429` and is audited.

Reject requires an approver, the matching plan hash, and a non-empty reason.
Cancel requires the requester or an approver, and works while the goal is
`pending_approval` or `approved`; a non-empty reason is required.

## Execution (Phase 2 + 3A, opt-in)

Execution is enabled only when **both** sides opt in:

```dotenv
# Ops
GOALS_ENABLED=true
GOALS_EXECUTE_ENABLED=true
GOALS_CONTROL_BASE=http://127.0.0.1:9182
GOALS_CONTROL_KEY=<shared secret, 32+ chars>

# Healer (VM105)
CONTROL_ENABLED=1
CONTROL_BIND=127.0.0.1
GOALS_EXECUTE=1
CONTROL_KEY=<same shared secret>

# Optional Phase 3A: Kubernetes Deployment rollback
K8S_ALLOW=aspirasi/web,aspirasi/api   # ns/nama, empty = k8s goals disabled
K8S_GOAL_NS=                          # optional namespace narrowing
K8S_PROTECT=aspirasi/payments         # always wins over K8S_ALLOW
K8S_GOAL_VERIFY=120                   # seconds to wait for available replicas
```

Ops refuses to start when the base URL is not loopback, the key is shorter than
32 chars, `GOALS_CONTROL_REQUEST_TIMEOUT >= GOALS_CONTROL_TIMEOUT`, or the poll
interval is under 0.5 s.

### Ops dispatch

`POST /api/goals/{id}/execute` is approver-only and requires `plan_hash` and
`confirm=true`; it is the second explicit click after approval. Ops verifies the
goal is `approved`, the hash matches, `execute_before` has not passed, and a
control client exists. It then atomically moves `approved → dispatching`,
increments `execute_count`, writes a `goal_runs` row (retries reuse the same
row and bump `attempts`), takes a lease, and returns `202` with
`accepted=true`. The HTTP call runs in a background task guarded by a
single-slot semaphore; the goal status and run id are re-checked after acquiring
the slot so a queued dispatch cannot run after the sweeper invalidated it.

The payload is exactly:

```json
{
  "plan_id": "…",
  "plan_hash": "…",
  "plan": { "...": "immutable plan" },
  "approved_by": "alice",
  "approved_at": "2026-10-22T10:00:00+00:00",
  "expires_at": "2026-10-22T10:10:00+00:00"
}
```

A `202` moves the goal to `executing` and starts polling
`GET /runs/{plan_id}` every `GOALS_CONTROL_POLL_INTERVAL` seconds until
`done`/`failed`/`unknown` or `GOALS_CONTROL_TIMEOUT`. The lease is renewed on
every poll; if renewal fails the goal becomes `unknown` rather than being
executed twice.

Rejection mapping:

| healer reply | Ops result |
| --- | --- |
| `202` accepted | `executing`, then journal-follow |
| `200` replay of a terminal run | finalize from the returned run |
| `409 busy`, `cooldown`, `incident_pending`, `run_in_progress`; `429 rate_limited`; `503 state_unavailable`, `approvals_unavailable` | goal returns to `approved` (run `rejected`, `attempts` kept) so an approver may retry before `execute_before` |
| `403 protected_target`, `non_auto_forbidden`, `target_not_allowed`; `409 plan_conflict`, `target_changed`, `state_changed`, `target_not_found`, `approval_expired`; `400 unsupported_target`, validation | `failed` — the plan is no longer valid; create a new preview |
| `409 execution_expired` | `expired` — `execute_before` passed; create a new goal |
| `5xx` | `unknown` — the claim may already exist |
| timeout / connection error | `unknown` (`control_timeout` / `control_unavailable`) |
| `401`/`403` during polling | `unknown` (`control_auth_failed`) |

There is **no automatic retry** anywhere in this path.

`POST /api/goals/{id}/reconcile` is approver-only and performs one signed
`GET /runs/{plan_id}`. It may turn `unknown` into `succeeded`/`failed` from the
journal, leave an active run active, or — when the journal has no record and the
goal is `unknown` — mark it `failed` with `not_dispatched`. It never triggers a
new execution.

### Control protocol

Every request carries `X-Laya-Timestamp`, `X-Laya-Nonce`, `X-Laya-Key-Id`, and
`X-Laya-Signature`. The signed message is:

```text
<timestamp>\n<nonce>\n<METHOD>\n<path>\n<sha256(body)>
```

signed with HMAC-SHA256. Timestamps must be within ±60 s and nonces are cached
for 120 s to block replay. `X-Laya-Key-Id` is the first 8 hex characters of
`sha256(key)`; during rotation the healer also accepts `CONTROL_KEY_PREVIOUS`.
The transport is loopback-only: the healer binds `127.0.0.1`, rejects non-loopback
peers, and refuses a non-loopback `CONTROL_BIND` unless
`CONTROL_ALLOW_REMOTE=1` (not recommended).

Endpoints: `GET /healthz` (no HMAC; reports `dry_run` and `execute_enabled`),
`POST /execute` (HMAC, exactly the six payload fields, ≤16 KiB),
`GET /runs/{plan_id}` (HMAC, journal status).

### Healer re-validation order (guest)

1. signature, timestamp, nonce, key id;
2. `GOALS_EXECUTE=1`, else `403 execute_disabled`;
3. `plan_id` replay: terminal journal record → `200 replayed=true`; `claimed`
   → `409 run_in_progress`; hash mismatch → `409 plan_conflict`;
4. `plan_hash == sha256(canonical_json(plan))`, exactly one step, executable
   action (`start`, `resume`, `reset`; `noop`/`escalate` rejected), target
   fields consistent;
5. `expires_at` in the future and `approved_at` within `GOALS_APPROVAL_TTL`;
6. no pending incident approval for the same vmid (`incident_pending`);
7. state exists, node/guest type/status match, `PROTECT` check, action allowed
   for the current status and guest type, cooldown (`COOLDOWN`);
8. `vmid ∈ AUTO_IDS` or `GOALS_ALLOW_NON_AUTO=1`;
9. `EXEC_LOCK` non-blocking; re-read state and re-check; rate limit
   `GOALS_MAX_PER_HOUR`;
10. journal `claimed` (fsync) then execute in a worker; write
    `decisions.jsonl` with `sumber="goal"`; update `aksi_ts` on real runs so
    incident cooldown sees the action.

A `claimed` record older than `GOALS_STALE_SECONDS` is resolved to `unknown`
with `stale_claim`; it is never re-executed automatically.

### Kubernetes execution (Phase 3A)

The healer routes each plan by `plan.target_kind`: `k8s_deployment` goes to
`proxmox/goal_k8s.py`, anything else to the Proxmox backend. Both backends share
one `goal_runs.jsonl` journal, so replay detection, `GET /runs/{plan_id}`, and
stale-claim handling are identical for both kinds. If no backend matches the
kind, the healer replies `400 unsupported_target`.

The k8s backend exists only when the healer set a non-empty `K8S_ALLOW`
(`proxmox_healer.py` imports `goal_k8s` + `k8s_heal`; a failure to load them
disables only k8s goals, never the Proxmox control plane). It validates, in
order:

1. `GOALS_EXECUTE=1`, else `403 execute_disabled`;
2. journal replay: terminal → `200 replayed=true`, `claimed` →
   `409 run_in_progress`, hash mismatch → `409 plan_conflict`;
3. `plan_hash == sha256(canonical_json(plan))`, exactly one step, action
   `rollout_undo`, template `k8s.deployment.rollback.v1`;
4. `expires_at` in the future, `approved_at` within `GOALS_APPROVAL_TTL`;
5. `namespace`/`deployment` match the DNS-1123 pattern and the plan; the pair is
   in `K8S_ALLOW`, not in `K8S_PROTECT`, and its namespace satisfies
   `K8S_GOAL_NS` when set;
6. fresh snapshot: `protected` → `403 protected_target`; not `allowed` →
   `403 target_not_allowed`; revision, previous revision, status, or
   `replicas == 0` differ from the plan → `409 state_changed`;
7. `EXEC_LOCK` non-blocking (`409 busy`), then the target checks are repeated
   because a rollout can start while waiting;
8. `GOALS_MAX_PER_HOUR` over the shared journal → `429 rate_limited`;
9. journal `claimed` (fsync), then a worker calls
   `k8s_heal.execute_rollout_undo(ns, dep, expected_revision)` under
   `K8S_LOCK`, which re-checks `K8S_PROTECT`/allow-list and the live revision,
   patches the Deployment to the previous ReplicaSet containers, and waits up
   to `K8S_GOAL_VERIFY` (default 120 s) for available replicas.

The run result records `from_revision`, `to_revision`, `images`,
`new_revision`, and `recovered`. `verify_timeout`, `no_previous_revision`,
`k8s_unavailable`, `state_changed`, `protected_target`, and `target_not_allowed`
end the run as `failed` with their `error_code`; nothing is retried. With
`DRY_RUN=1` the command is not applied: the result carries the planned
revision/image transition and `dry_run=true`. K8s runs are written to
`decisions.jsonl` with `sumber="goal"`, `jenis_target="deployment"`, and
`jenis="goal"`; they do not touch guest `aksi_ts` or the guest cooldown.

## TTLs and clocks

| setting | default | effect |
| --- | --- | --- |
| `GOALS_PREVIEW_TTL` | 300 s | preview expiry (minimum 30 s) |
| `GOALS_APPROVAL_TTL` | 900 s | pending-approval window after create |
| `GOALS_EXECUTION_TTL` | 600 s | `execute_before` set at approval |
| `GOALS_RATE_LIMIT_PER_HOUR` | 10 | goals created per requester per rolling hour |

Control timing (execution only):

| setting | default | effect |
| --- | --- | --- |
| `GOALS_CONTROL_TIMEOUT` | 150 s | total time to follow one run before `unknown` (minimum 5 s) |
| `GOALS_CONTROL_REQUEST_TIMEOUT` | 15 s | per-request timeout; must be shorter than the total |
| `GOALS_CONTROL_POLL_INTERVAL` | 2 s | journal poll interval (minimum 0.5 s) |

A pending goal past `expires_at`, or an approved goal past `execute_before`, is
marked `expired` on load or by the 30-second sweeper. A `dispatching`/`executing`
goal whose run lease expired is marked `unknown` (`lease_expired`) by the same
sweeper; it is never retried. A dedicated timer is not needed for correctness;
the sweeper is cleanup.

## Configuration

All switches live in `.env.example`; every goal feature is off by default.

Required to enable Phase 1:

```dotenv
AUTH_MODE=password            # or oidc; never off
SESSION_SECRET=<random 32+ bytes>
PUBLIC_ORIGIN=https://laya.example.lan   # exact scheme+host+port
GOALS_ENABLED=true
GOALS_DATA_DIR=/app/data
GOALS_APPROVERS=alice,bob     # and/or GOALS_APPROVER_GROUPS=sre-approvers
GOALS_ALLOW_SELF_APPROVAL=false
GOALS_EXECUTE_ENABLED=false   # leave false until the healer is ready
```

To enable Phase 2, also set `GOALS_EXECUTE_ENABLED=true`, a loopback
`GOALS_CONTROL_BASE`, `GOALS_CONTROL_KEY`, and the matching
`CONTROL_ENABLED=1` / `GOALS_EXECUTE=1` / `CONTROL_KEY` on the healer. Start
with `DRY_RUN=1` and rehearse before flipping dry-run off.

The `k8s.deployment.rollback.v1` template only works when the healer exposes at
least one entry in `K8S_ALLOW`; without it `goal_k8s` is not loaded and the
template's target list returns `k8s_disabled`. A preview then answers
`404 target_not_allowed` because no Deployment is listable. Guest goals are
unaffected.

Startup fails closed when:

- goals are enabled with `AUTH_MODE=off`;
- goals are enabled with the default `SESSION_SECRET`;
- goals are enabled without `PUBLIC_ORIGIN`;
- `GOALS_EXECUTE_ENABLED=true` without `GOALS_ENABLED=true`;
- `GOALS_AUTO_EXECUTE_AFTER_APPROVAL=true` (unsupported by design);
- execution is enabled with a non-loopback `GOALS_CONTROL_BASE`;
- execution is enabled with a `GOALS_CONTROL_KEY` shorter than 32 chars;
- execution is enabled with `GOALS_CONTROL_TIMEOUT < 5`, a request timeout below
  1 s or not shorter than the total, or a poll interval below 0.5 s;
- `GOALS_LLM_ENABLED=true` without `GOALS_LLM_URL`;
- the data directory cannot be created/written, or the DB schema version is
  newer than the code.

## Optional LLM planner

Rules are always the default and always validate. The optional LLM applies to
the guest template only; `k8s.deployment.rollback.v1` is always rules-built.
With `GOALS_LLM_ENABLED=true` and `GOALS_LLM_URL` set, Ops calls an
OpenAI-compatible `POST <GOALS_LLM_URL>/chat/completions` with
`temperature=0`, `max_tokens<=400`, and a JSON response hint. The model only
returns `{action, risk, rationale, warnings, needs_input}`; the server builds
the plan.

The system prompt and JSON envelope mark the operator goal as
`<untrusted>...</untrusted>`. The model has no tools, never sees the approval
code, `GOALS_LLM_KEY`, `GOALS_CONTROL_KEY`, or other secrets, and cannot change
the target. Its chosen action must be in the server's state-specific candidate
set; its risk may not be lower than the server's; text is cleaned and truncated.
Timeout, HTTP error, invalid JSON, or an out-of-catalog action falls back to
rules with the warning `AI planner tidak tersedia; aturan deterministik dipakai.`

`GOALS_LLM_KEY` is server-side only. It is never entered in the browser and
never written to a plan, audit row, or response.

## API surface

All routes live under `/api/goals` and exist only when `GOALS_ENABLED=true`
(otherwise 404). They require a session and the normal `RequestGuard` checks:
exact `Origin`, `X-CSRF-Token`, `Content-Type: application/json` for bodies, and
the body-size limit. Responses carry `Cache-Control: no-store`.

| method | path | who |
| --- | --- | --- |
| GET | `/templates` | any authenticated user |
| GET | `/targets?template_id=` | any authenticated user; guest or Deployment picker rows |
| POST | `/preview` | any authenticated user |
| POST | `/api/goals` (create) | any authenticated user |
| GET | `/api/goals?status=&limit=&cursor=` | requester sees own; approver sees all |
| GET | `/{id}` | owner or approver |
| GET | `/{id}/audit` | owner or approver |
| POST | `/{id}/approve` | approver |
| POST | `/{id}/reject` | approver |
| POST | `/{id}/cancel` | requester or approver |
| POST | `/{id}/execute` | approver; `202` accepted, `409 execution_disabled` when off |
| POST | `/{id}/reconcile` | approver; read-only journal check |

The create response is the only response that can contain `approval_code`.
Replaying the same `idempotency_key` returns the original goal with
`approval_code=null` and `idempotent_replay=true`. The code cannot be recovered;
cancel the goal and create a new one if it is lost.

## Data, audit, and secrets

- SQLite file: `GOALS_DATA_DIR/goals.db`, directory mode `0700`, DB mode `0600`,
  WAL enabled. In Docker it is the `laya-ops-data` named volume mounted at
  `/app/data`.
- Tables: `goal_previews`, `goal_requests`, `goal_runs`, `goal_audit`,
  `schema_meta`. Schema version 3 adds `target_kind` to `goal_previews` and
  `goal_requests`; k8s goals store `target_node=<namespace>`,
  `target_type=deployment`, `target_vmid=0`, and the full revision/image
  snapshot in `target_json`. The plan itself is unchanged and remains the
  source of truth.
- Audit events include preview creation (keyed by preview id), goal creation,
  failed approvals, approval throttling, approve, reject, cancel, execute
  request/accept/retryable/finish, reconcile, and sweeper expiry. A goal's
  `/audit` timeline begins at `goal.created`; the preview row has its own id.
  Actor `sub`, display name, auth method, client IP, user agent, plan hash,
  action, vmid (or namespace/deployment), run id, and outcome are recorded.
  Approval codes, passphrases, API keys, and the HMAC key are never recorded.
- Audit is append-only through the application: there is no update/delete
  endpoint. Protect the volume and take backups before upgrades.
- Healer-side execution is recorded in `HEALER_DIR/goal_runs.jsonl` (append-only,
  fsync, 0600) and in `decisions.jsonl` with `sumber="goal"`. Journal records
  contain the plan id/hash, action, vmid or `namespace/deployment` (`node`),
  approver name, dry-run flag, result, error, and timestamps — never the
  control key.
- Only one Ops worker is supported. SQLite and the in-process store lock assume a
  single process; do not scale the container horizontally.

## Troubleshooting

| symptom | check |
| --- | --- |
| `/api/goals/*` returns 404 | `GOALS_ENABLED` is false; restart after changing `.env` |
| startup: `GOALS_ENABLED=true requires AUTH_MODE=...` | set password or OIDC; goals never run with auth off |
| startup: `requires PUBLIC_ORIGIN` | set the exact browser origin, including scheme and port |
| startup: `schema ... newer than this app` | you downgraded the image; restore a compatible DB backup, do not delete the volume blindly |
| 403 `approver role required` | identity is not in `GOALS_APPROVERS`/groups, or password approval is not opted in |
| 403 `self_approval_forbidden` | requester is the approver; use a second OIDC identity or explicitly opt into self-approval |
| 403 `invalid_approval_code` | wrong code; 5 failures in 15 minutes triggers 429 |
| 400 `typed_confirmation_required` | enter exactly the `requirements.typed_confirmation` phrase (`SETUJU <action> <vmid>` or `SETUJU rollout_undo <ns>/<dep>`) |
| 403 `high_risk_passphrase_invalid` | high-risk passphrase is configured and did not match |
| 409 `preview_expired` / `preview_used` | preview TTL elapsed or already consumed; preview again |
| 409 `state_changed` | target state changed between preview and create; preview again |
| 409 `protected_target` | vmid is in `PROTECT` (or Deployment in `K8S_PROTECT`); choose another target or escalate manually |
| preview `blocked` | see `blocked_reason`; no create/approve button is offered |
| 404 `target_not_allowed` on preview | Deployment is not in the healer `K8S_ALLOW`, or its namespace is outside `K8S_GOAL_NS` |
| `/targets` error `k8s_disabled` | healer `K8S_ALLOW` is empty, or `goal_k8s.py`/`k8s_heal.py` failed to import; check the healer startup log |
| `/targets` error `k8s_unavailable` | healer `/api/k8s` cannot reach the cluster; guest goals still work |
| 400 `unsupported_target` | the plan's `target_kind` has no backend on the healer; deploy `goal_k8s.py` or keep k8s templates off |
| k8s run `target_not_allowed` | allow-list changed between preview and execution; preview again |
| k8s run `state_changed` | Deployment revision or availability changed; preview again |
| k8s run `no_previous_revision` | no earlier ReplicaSet with different images; escalate instead |
| k8s run `verify_timeout` | rollback was applied but available replicas did not recover within `K8S_GOAL_VERIFY`; inspect the Deployment before any new goal |
| 409 `execution_disabled` | `GOALS_EXECUTE_ENABLED=false`; execute cannot run |
| 403 `approver role required` on execute | only approvers may send the second click |
| 409 `plan_hash_mismatch` | plan changed or request came from an old tab; reload the goal |
| 410 `execution_expired` | `execute_before` passed; the approved plan is no longer valid |
| goal stuck in `dispatching` | check the healer control port and Ops logs; the sweeper marks stale leases `unknown` |
| `unknown` after execute | do not re-execute; click **Reconcile**. `not_dispatched` means the journal has no record |
| healer `401`/`control_auth_failed` | `CONTROL_KEY` differs between Ops and healer, or clock skew exceeds 60 s |
| healer `403 execute_disabled` | `GOALS_EXECUTE=1` is not set on the healer |
| healer `403 non_auto_forbidden` | target is not in `AUTO_IDS` and `GOALS_ALLOW_NON_AUTO=0` |
| `429 rate_limited` | `GOALS_MAX_PER_HOUR` reached; wait for the rolling hour |
| run result `dry_run=true` | healer had `DRY_RUN=1`; the target was not changed |

## Not in this phase

- K8s actions other than Deployment `rollout_undo`; StatefulSets, DaemonSets,
  Services, and free-form kubectl are never accepted.
- LLM planning for k8s targets — Phase 3A is rules-only.
- Multi-step plans, per-step rollback, batch targets, maintenance windows.
- Shell/SSH/kubectl/URL/PromQL input of any kind.
- Automatic execution after approval, or automatic retry after `unknown`.
- Multi-worker/HA and off-box audit.
- Remote (non-loopback) control transport, TLS/mTLS, or a Unix socket.
