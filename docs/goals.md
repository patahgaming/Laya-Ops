# AI Goals (Phase 1)

AI Goals lets an authenticated operator describe **what** should happen to one
Proxmox guest, supply a small set of variables, preview a server-built plan, and
send it to a human approver. The AI never executes anything. In Phase 1 the
feature stops at `approved`; there is no dispatch path to the healer.

> **Phase 1 scope:** plan, preview, approval, rejection, cancellation, audit.
> `POST /api/goals/{id}/execute` and `/reconcile` always return
> `409 execution_disabled`. Phase 2 (healer control API, HMAC, journal and
> `EXEC_LOCK`) is not implemented yet.

## Trust boundary

```text
operator
  │  goal text + variables (untrusted data, never commands)
  ▼
Laya Ops UI ── session + exact Origin + CSRF ──► Ops API
                                                   │
                          server resolves target from healer state
                          rules planner validates; optional LLM only advises
                                                   │
                          immutable plan + sha256 plan hash in SQLite
                                                   │
                          human approver + one-time code (+ passphrase)
                                                   │
                                          approved (Phase 1 stops here)
                                                   │
                          Phase 2 only: HMAC → healer 127.0.0.1:9182
                                                   │
                                    healer re-validates PROTECT/state/action
                                                   │
                                          qm|pct start|resume|reset
```

Hard rules:

- **AI proposes, server validates, human approves, healer executes.**
- The planner may only choose from `start`, `resume`, `reset`, `noop`,
  `escalate`. `noop` and `escalate` are not executable.
- The target (`vmid`, node, guest type, status) is resolved server-side from
  `/api/state`; neither the browser nor the model may supply or change it.
- `PROTECT` is absolute. A protected target produces a `blocked` preview and
  cannot be created. The healer will re-check `PROTECT` before any Phase 2
  execution.
- No shell, SSH, kubectl, URL, PromQL, or free-form command is accepted as a
  goal or variable.
- `DRY_RUN=1` remains the healer default. Phase 1 does not change healer state.

## Lifecycle (Phase 1)

```text
pending_approval ──approve──► approved ──execute──► ...   (Phase 2)
       │
       ├──reject──► rejected
       ├──cancel──► cancelled
       └──expire──► expired

approved ──cancel──► cancelled
approved ──expire──► expired
```

Only `pending_approval`, `approved`, `rejected`, `cancelled`, and `expired` are
reachable in Phase 1. `dispatching`, `executing`, `succeeded`, `failed`, and
`unknown` are reserved for Phase 2 and already exist in the schema/status
literals.

A preview may be `ready` or `blocked`. `needs_input` is reserved by the response
type but is not returned by the current template; required variables are
enforced by request validation instead. Blocked reasons:

| reason | meaning |
| --- | --- |
| `protected_target` | the vmid is in the healer `PROTECT` knob |
| `target_metadata_missing` | state has no usable `node`/`jenis` for this guest |
| `no_safe_action` | observed state has no executable safe action (only `noop`/`escalate`) |

## Template and variables

Phase 1 has one code-defined template, `guest.recover.v1`. Templates live in
`backend/app/goals/templates.py`; there is no UI or database editor for them.

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

If the target is not in `AUTO_IDS`, the plan carries a warning. In Phase 2 the
healer would additionally require `GOALS_ALLOW_NON_AUTO=1`; Phase 1 never
executes.

## Immutable plan and hash

The server builds the complete plan. `plan_hash` is
`sha256(canonical_json(plan))` with sorted keys and compact separators. The plan
JSON is written once; the store's update allow-list cannot modify plan fields.
Approval binds the hash supplied by the approver to the stored hash.

A create request must present the preview's `preview_id`, exact `plan_hash`, and
a caller-generated `idempotency_key` (8–128 chars, unique per requester). Before
creating the goal, the server re-fetches state and rejects with
`409 state_changed` if vmid, node, guest type, status, agent liveness, or
`PROTECT` changed since preview. Preview is single-use.

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
   the typed phrase `SETUJU <action> <vmid>`.

A plan is high-risk when the action is `reset` **or** the target is not in
`AUTO_IDS`. The code is 12 characters from an unambiguous alphabet, stored only
as a salted PBKDF2-HMAC-SHA256 hash (210,000 iterations), and is cleared when the
goal is approved, rejected, or cancelled. It is returned in plaintext **once**,
in the create response; it cannot be recovered later. Maximum 5 failed code
attempts per 15 minutes, after which approval returns `429` and is audited.

Reject requires an approver, the matching plan hash, and a non-empty reason.
Cancel requires the requester or an approver, and works while the goal is
`pending_approval` or `approved`; a non-empty reason is required.

## TTLs and clocks

| setting | default | effect |
| --- | --- | --- |
| `GOALS_PREVIEW_TTL` | 300 s | preview expiry (minimum 30 s) |
| `GOALS_APPROVAL_TTL` | 900 s | pending-approval window after create |
| `GOALS_EXECUTION_TTL` | 600 s | `execute_before` set at approval (Phase 2) |
| `GOALS_RATE_LIMIT_PER_HOUR` | 10 | goals created per requester per rolling hour |

A pending goal past `expires_at`, or an approved goal past `execute_before`, is
marked `expired` on load or by the 30-second sweeper. A dedicated timer is not
needed for correctness; the sweeper is cleanup.

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
GOALS_EXECUTE_ENABLED=false   # keep false in Phase 1
```

Startup fails closed when:

- goals are enabled with `AUTH_MODE=off`;
- goals are enabled with the default `SESSION_SECRET`;
- goals are enabled without `PUBLIC_ORIGIN`;
- `GOALS_EXECUTE_ENABLED=true` without `GOALS_ENABLED=true`;
- `GOALS_AUTO_EXECUTE_AFTER_APPROVAL=true` (unsupported by design);
- execution is enabled with a non-loopback `GOALS_CONTROL_BASE`;
- execution is enabled with a `GOALS_CONTROL_KEY` shorter than 32 chars;
- `GOALS_LLM_ENABLED=true` without `GOALS_LLM_URL`;
- the data directory cannot be created/written, or the DB schema version is
  newer than the code.

**Phase 1 warning:** leave `GOALS_EXECUTE_ENABLED=false`. Setting it `true` does
not add a dispatch path in this release; execute still returns
`409 execution_disabled`. Do not set a control key yet.

## Optional LLM planner

Rules are always the default and always validate. With
`GOALS_LLM_ENABLED=true` and `GOALS_LLM_URL` set, Ops calls an
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
| POST | `/preview` | any authenticated user |
| POST | `/api/goals` (create) | any authenticated user |
| GET | `/api/goals?status=&limit=&cursor=` | requester sees own; approver sees all |
| GET | `/{id}` | owner or approver |
| GET | `/{id}/audit` | owner or approver |
| POST | `/{id}/approve` | approver |
| POST | `/{id}/reject` | approver |
| POST | `/{id}/cancel` | requester or approver |
| POST | `/{id}/execute` | approver; always 409 in Phase 1 |
| POST | `/{id}/reconcile` | approver; always 409 in Phase 1 |

The create response is the only response that can contain `approval_code`.
Replaying the same `idempotency_key` returns the original goal with
`approval_code=null` and `idempotent_replay=true`. The code cannot be recovered;
cancel the goal and create a new one if it is lost.

## Data, audit, and secrets

- SQLite file: `GOALS_DATA_DIR/goals.db`, directory mode `0700`, DB mode `0600`,
  WAL enabled. In Docker it is the `laya-ops-data` named volume mounted at
  `/app/data`.
- Tables: `goal_previews`, `goal_requests`, `goal_runs`, `goal_audit`,
  `schema_meta`.
- Audit events include preview creation (keyed by preview id), goal creation,
  failed approvals, approval throttling, approve, reject, and cancel. A goal's
  `/audit` timeline begins at `goal.created`; the preview row has its own id.
  Actor `sub`, display name, auth method, client IP, user agent, plan hash,
  action, vmid, and outcome are recorded. Approval codes, passphrases, and API
  keys are never recorded.
- Audit is append-only through the application: there is no update/delete
  endpoint. Protect the volume and take backups before upgrades.
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
| 400 `typed_confirmation_required` | enter exactly `SETUJU <action> <vmid>` from `requirements.typed_confirmation` |
| 403 `high_risk_passphrase_invalid` | high-risk passphrase is configured and did not match |
| 409 `preview_expired` / `preview_used` | preview TTL elapsed or already consumed; preview again |
| 409 `state_changed` | guest state changed between preview and create; preview again |
| 409 `protected_target` | vmid is in `PROTECT`; choose another target or escalate manually |
| preview `blocked` | see `blocked_reason`; no create/approve button is offered |
| 409 `execution_disabled` | expected in Phase 1; there is no execution path |

## Not in this phase

- K8s actions (`rollout_undo`), multi-step plans, per-step rollback.
- Shell/SSH/kubectl/URL/PromQL input of any kind.
- Automatic execution after approval.
- Multi-worker/HA and off-box audit.
- Any healer control request. Port `9182` is Phase 2 and, when the healer
  control skeleton is enabled, exposes only `GET /healthz`.
