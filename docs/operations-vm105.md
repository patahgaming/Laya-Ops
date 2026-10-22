# VM105 operations — AI Goals (Phase 1 + Phase 2 + Phase 3A)

This checklist deploys and rehearses AI Goals. Phase 1 (preview, create,
approve, reject, cancel, audit) is safe to enable first; Phase 2 execution is a
separate opt-in covered in [section 7](#7-phase-2-enable-execution-opt-in) and
must not be enabled until the healer side is deployed and rehearsed. Phase 3A
(Kubernetes Deployment `rollout_undo`) is an additional opt-in layered on Phase 2
and is covered in [section 8](#8-phase-3a-kubernetes-deployment-rollback).

> **Default posture:** `GOALS_EXECUTE_ENABLED=false` on Ops and
> `GOALS_EXECUTE=0` on the healer. Execution requires both sides plus a shared
> `CONTROL_KEY`, and the healer still defaults to `DRY_RUN=1`. Kubernetes goals
> stay disabled while `K8S_ALLOW` is empty.

## 1. Preflight

On the VM105 host, from the release directory (examples below use
`/opt/laya-ops`):

```bash
cd /opt/laya-ops
docker compose config --quiet
docker compose ps
curl -sS http://127.0.0.1:9190/api/healthz
curl -sS http://127.0.0.1:9190/api/auth/config | python3 -m json.tool
```

Confirm before changing anything:

- The console is healthy and the current release still behaves read-only.
- `features.goals` is `false` in `/api/auth/config` (or matches the previous
  intentional state).
- `laya-ops-data` volume exists if goals were previously enabled; it is the only
  copy of goal previews, approvals and audit.
- You know the exact browser origin, including scheme and port. Behind TLS this
  is e.g. `https://laya.example.lan`; direct access is e.g.
  `http://10.10.0.107:9190`. `PUBLIC_ORIGIN` must match byte-for-byte, without a
  trailing slash.
- Choose a **non-critical lab guest** for the rehearsal. Never start with VM105,
  a production service, or anything in `PROTECT`.
- Decide the approval mode:
  - **OIDC (recommended):** two distinct users for true two-person approval.
  - **Password:** single identity `operator`; requires explicit single-person
    opt-in and the UI will show a warning.

### Backup the goals volume

Do this before an upgrade, and always before changing a volume or restoring a
database. The backup contains plan text and the audit trail; treat it as
sensitive. On a first install the volume does not exist yet — skip this step.

```bash
cd /opt/laya-ops
mkdir -p backups
stamp=$(date +%Y%m%d-%H%M%S)
docker compose stop laya-ops
docker run --rm \
  -v laya-ops-data:/data \
  -v "$PWD/backups":/backup \
  alpine tar czf "/backup/laya-ops-data-$stamp.tgz" -C /data .
docker compose start laya-ops
ls -lh "backups/laya-ops-data-$stamp.tgz"
```

The stop is intentional: a plain copy of `goals.db` while SQLite is in WAL mode
can miss recent commits.

## 2. Configure goals (Phase 1)

Edit `.env` on the host. Keep the file mode restrictive (`chmod 600 .env`).
Never commit it or paste secrets into tickets/chat.

Minimum OIDC-oriented configuration:

```dotenv
AUTH_MODE=oidc
OIDC_ISSUER=https://sso.example/realms/school
OIDC_CLIENT_ID=laya-ops
OIDC_CLIENT_SECRET=<from-secret-store>
OIDC_REDIRECT_URI=https://laya.example.lan/api/auth/oidc/callback
SESSION_SECRET=<32+ random bytes>
COOKIE_SECURE=true

ALLOWED_HOSTS=laya.example.lan,10.10.0.107,localhost
PUBLIC_ORIGIN=https://laya.example.lan

GOALS_ENABLED=true
GOALS_DATA_DIR=/app/data
GOALS_EXECUTE_ENABLED=false
GOALS_AUTO_EXECUTE_AFTER_APPROVAL=false

GOALS_APPROVERS=alice,bob
# GOALS_APPROVER_GROUPS=sre-approvers
GOALS_ALLOW_SELF_APPROVAL=false
GOALS_ALLOW_PASSWORD_APPROVAL=false

GOALS_PREVIEW_TTL=300
GOALS_APPROVAL_TTL=900
GOALS_EXECUTION_TTL=600
GOALS_RATE_LIMIT_PER_HOUR=10
```

Notes:

- `PUBLIC_ORIGIN` is required when goals are enabled and is checked on every
  unsafe request; the reverse proxy must preserve the browser's scheme/host.
- Keep OIDC groups available in userinfo. If group-based approval is used, add a
  Keycloak group-membership mapper; otherwise use explicit usernames.
- The OIDC callback URL must match `OIDC_REDIRECT_URI` and the Keycloak client
  configuration exactly.
- For a password-mode rehearsal instead:

  ```dotenv
  AUTH_MODE=password
  GOALS_APPROVERS=operator
  GOALS_ALLOW_PASSWORD_APPROVAL=true
  GOALS_ALLOW_SELF_APPROVAL=true
  ```

  This is deliberately single-person. Do not present it as two-person approval.

- Leave `GOALS_LLM_ENABLED=false` unless the optional planner has been reviewed
  and `GOALS_LLM_URL` is configured. The LLM key stays in the server environment.

## 3. Deploy and verify startup

```bash
cd /opt/laya-ops
docker compose up -d --build
docker compose ps
docker compose logs --tail=100 laya-ops
curl -sS http://127.0.0.1:9190/api/healthz
curl -sS http://127.0.0.1:9190/api/auth/config | python3 -m json.tool
```

Expected:

- container is healthy;
- `/api/healthz` returns `{"ok": true, ...}`;
- `/api/auth/config` shows `features.goals: true`,
  `features.goals_execute: false`, and the expected `approval_mode`;
- no startup exception, especially none of the fail-closed goal errors listed in
  [goals.md](goals.md).

If the app refuses to start, **do not bypass the check** and do not delete the
data volume. Read the startup error; it names the missing or unsafe setting.

Check the healer control port state:

```bash
# Phase 1: nothing needs to listen on 9182. If the healer control server is
# enabled it must report execute_enabled=false.
ss -ltnp | grep ':9182' || true
curl -sS http://127.0.0.1:9182/healthz || true
```

Phase 1 Ops never POSTs to `:9182`. The only healer traffic is its existing
read API (`/api/state`, `/api/knobs`, `/api/decisions`, `/api/pending`).

## 4. UI rehearsal

Log in through the public origin (not `127.0.0.1` if that is not in
`PUBLIC_ORIGIN`).

1. **Navigation and flags**
   - `AI Goals` appears under Control.
   - The page states that execution is disabled and AI never executes.
2. **Preview**
   - Select `guest.recover.v1`.
   - Select the lab guest.
   - Enter a reason and a benign goal such as `rehearsal phase 1`.
   - Preview. Confirm the plan shows the expected vmid, node, guest type,
     status, action, risk, `generated_by=rules` (unless the LLM is enabled), a
     64-character plan hash, and the evidence hash.
   - Confirm a guest in `PROTECT` produces a blocked preview and cannot be
     created.
3. **Create and one-time code**
   - Create the goal. Confirm the approval-code banner appears once.
   - Copy the code; it is not stored in the browser and cannot be recovered.
   - Refresh and reopen the goal: no code is shown. If the code is lost, cancel
     and create a new goal.
4. **Approval**
   - As the approver (a different OIDC user when two-person is configured),
     review the target and action, enter the code, tick confirmation, and
     approve.
   - For a non-AUTO target, enter the exact typed confirmation
     `SETUJU <action> <vmid>` shown by the page, unless a high-risk passphrase is
     configured.
   - Confirm the final status is `approved` and `execute_before` is set. With
     `GOALS_EXECUTE_ENABLED=false`, no **Execute** action is offered; with it
     enabled, the approver sees the second-click **Execute…** button.
5. **Negative paths**
   - Wrong code → `invalid_approval_code`; five failures within 15 minutes →
     throttled.
   - Self-approval as the requester with `GOALS_ALLOW_SELF_APPROVAL=false` →
     forbidden.
   - Reject a second goal with a reason → `rejected`.
   - Cancel a pending or approved goal with a reason → `cancelled`.
   - Let a preview or pending goal expire (or shorten the TTLs in a lab) and
     confirm it becomes `expired`.
6. **Audit**
   - Open the goal drawer and confirm create/approve or reject/cancel events,
     actor names, timestamps and plan hash. (Preview creation is audited under
     the preview id; the goal timeline starts at `goal.created`.)
   - Confirm no approval code, passphrase, or API key appears anywhere in the
     audit view.
7. **No execution (Phase 1)**
   - With `GOALS_EXECUTE_ENABLED=false`, `Execute` is absent/disabled.
   - A direct execute request is rejected with `409 execution_disabled`.
   - The Healer page's `goal_24h` remains `0`; `insiden_24j` is unchanged.
   - Healer state and `decisions.jsonl` show no new action caused by the goal.

Optional read-only DB check:

```bash
docker exec laya-ops python -c \
  "import sqlite3; c=sqlite3.connect('/app/data/goals.db'); \
print(c.execute('select status, count(*) from goal_requests group by status').fetchall()); \
print(c.execute('select event, ts from goal_audit order by id desc limit 10').fetchall())"
```

## 5. Two-person OIDC test

If OIDC is configured for real separation:

1. User A (requester) creates and previews a goal.
2. User A attempts approval → `self_approval_forbidden` (403).
3. User B, in `GOALS_APPROVERS` or an approver group, receives the code out of
   band from A and approves.
4. Confirm the audit shows A as requester and B as approver, with distinct
   `sub` values.
5. Confirm a user in neither list sees no goals and gets `403` on approval.

If group membership is missing, check the Keycloak `groups` claim in userinfo;
fix the mapper before relying on group-based approval.

## 6. Rollback

Fast rollback keeps all history:

```bash
cd /opt/laya-ops
# .env: set GOALS_ENABLED=false
docker compose up -d
curl -sS http://127.0.0.1:9190/api/auth/config   # features.goals == false
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9190/api/goals/templates  # 404
```

- Nav and route disappear; goal routes return 404.
- The `laya-ops-data` volume is **not** deleted. Approvals/audit remain for a
  later re-enable.
- If a schema migration was involved and you must restore a backup, stop the
  container first and restore the whole volume, not just `goals.db`; a mismatched
  WAL file can corrupt or silently roll back state. Restore only from a backup
  taken for this purpose and verify the schema version before starting.
- Never run `docker compose down -v` on this project unless you explicitly
  intend to destroy the goals database. `down -v` removes the named volume.

## 7. Phase 2: enable execution (opt-in)

Only proceed after the Phase 1 rehearsal above and after deploying the healer
release that includes `goal_control.py`, `goal_journal.py` and
`goal_executor.py`. Start with `DRY_RUN=1`; keep `GOALS_EXECUTE=0` on the healer
until Ops is dispatched with the key configured and verified.

### 7.1 Generate and place the shared key

```bash
# Generate once, on a trusted machine. Do not paste it into chat or tickets.
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

- Ops `.env` (mode 600): `GOALS_CONTROL_KEY=<key>`.
- Healer env (`/etc/proxmox-healer.env`, mode 600): `CONTROL_KEY=<same key>`.
- The key must be at least 32 characters. No other component needs it.

### 7.2 Healer configuration

```dotenv
CONTROL_ENABLED=1
CONTROL_BIND=127.0.0.1
CONTROL_PORT=9182
CONTROL_KEY=<shared key>
CONTROL_KEY_PREVIOUS=
GOALS_EXECUTE=1
GOALS_ALLOW_NON_AUTO=0
GOALS_MAX_PER_HOUR=4
GOALS_APPROVAL_TTL=900
GOALS_STALE_SECONDS=300
DRY_RUN=1
```

`CONTROL_BIND` must stay loopback. Do not set `CONTROL_ALLOW_REMOTE=1` outside a
controlled lab. Restart the healer and verify:

```bash
ss -ltnp | grep ':9182'          # must be 127.0.0.1:9182, never 0.0.0.0
curl -sS http://127.0.0.1:9182/healthz
# {"ok": true, "version": "...", "dry_run": true, "execute_enabled": true}
```

`/healthz` does not require HMAC; `/execute` and `/runs/{plan_id}` do.

### 7.3 Ops configuration

```dotenv
GOALS_EXECUTE_ENABLED=true
GOALS_CONTROL_BASE=http://127.0.0.1:9182
GOALS_CONTROL_KEY=<shared key>
GOALS_CONTROL_TIMEOUT=150
GOALS_CONTROL_REQUEST_TIMEOUT=15
GOALS_CONTROL_POLL_INTERVAL=2
```

Restart Ops and confirm `/api/auth/config` reports
`features.goals_execute: true`.

### 7.4 Dry-run rehearsal (`DRY_RUN=1`)

Use a non-critical lab guest; never VM105 or a `PROTECT` target.

1. Create and approve a goal as in section 4. With execution on, the approved
   goal shows **Execute…** only for an approver.
2. Click **Execute…**, tick the confirmation, and click `Execute <action>`.
   This is the second explicit click; there is no auto-execute.
3. Confirm the goal moves through `dispatching`/`executing` to `succeeded`, the
   run journal shows `dry_run=true`, and the guest state did **not** change.
4. Confirm `decisions.jsonl` contains one entry with `sumber="goal"`, the plan
   id/hash and the approver name, and that `goal_24h` increases while
   `insiden_24j` does not.
5. Repeat the same execute request (replay): the healer returns the old run and
   no second action is performed.
6. Wrong-key test: temporarily set a different `GOALS_CONTROL_KEY` on Ops.
   Execute must end `unknown` with `control_auth_failed`; **Reconcile** must not
   cause an action. Restore the key.
7. Stop the healer and execute another goal: it must end `unknown`
   (`control_unavailable`), and reconcile must report the journal state once the
   healer is back. There is no automatic retry.

### 7.5 One real action (`DRY_RUN=0`)

1. Set `DRY_RUN=0` on the healer and restart it.
2. Deliberately stop the lab guest, then run the full preview → approve →
   execute flow.
3. Verify the guest starts, the run journal shows `dry_run=false`, and
   `decisions.jsonl` records the action. Confirm `aksi_ts` was updated so the
   incident loop respects the cooldown.
4. Execute a plan for a target that is not in `AUTO_IDS` while
   `GOALS_ALLOW_NON_AUTO=0`: the healer must return
   `403 non_auto_forbidden`, and the goal must end `failed`.
5. Execute a plan for a `PROTECT` target if one can be forced through the API
   (it cannot be created from the UI): the healer must return
   `403 protected_target`.
6. Kill the healer between claim and finish. After restart, the stale claim must
   become `unknown`; **do not** re-execute. Reconcile is the only allowed action.

### 7.6 Rollback

- Set `GOALS_EXECUTE_ENABLED=false` on Ops (or `GOALS_EXECUTE=0` on the healer),
  restart, and confirm execute returns `409 execution_disabled`.
- Setting `GOALS_ENABLED=false` disables the whole feature as in section 6.
- Never delete `goal_runs.jsonl`; it is the replay-protection record.
- Rotate `CONTROL_KEY` by setting the old value in `CONTROL_KEY_PREVIOUS` on the
  healer, deploying the new key on both sides, then clearing the previous value.

## 8. Phase 3A: Kubernetes Deployment rollback

Phase 3A adds one closed action: `rollout_undo` on a Deployment listed in the
healer's `K8S_ALLOW`. It reuses the Phase 2 control API, HMAC protocol, journal,
`EXEC_LOCK`, approval code, and typed confirmation. Do not start here: finish
the Phase 1 and Phase 2 rehearsals first.

> **Scope:** Deployment only. StatefulSets, DaemonSets, Services, and free-form
> kubectl are rejected by construction. The target must be in `K8S_ALLOW` and
> must never be in `K8S_PROTECT`; `K8S_PROTECT` always wins.

### 8.1 Deploy the healer modules

The healer release must include `proxmox/goal_k8s.py` **and** `proxmox/k8s_heal.py`
alongside the Phase 2 files (`goal_control.py`, `goal_journal.py`,
`goal_executor.py`). If `goal_k8s.py` is missing, the import failure disables
k8s goals (logged as `goal k8s backend tidak aktif`) while guest goals keep
working.

Confirm the healer can read the cluster and sees the allow-listed targets:

```bash
curl -sS http://127.0.0.1:9182/healthz
curl -sS http://127.0.0.1:9181/api/k8s | python3 -m json.tool
```

`/api/k8s` must list the Deployment under the expected namespace with
`allowed=true`, `protected=false`, and sane `revision`/`previous_revision`.
Guest state and decisions are unaffected by this check.

### 8.2 Healer configuration

```dotenv
# same control settings as section 7.2
K8S_ALLOW=aspirasi/web
K8S_GOAL_NS=
K8S_PROTECT=
K8S_GOAL_VERIFY=120
DRY_RUN=1
```

- `K8S_ALLOW` is comma-separated `namespace/name`. Empty means the k8s goal
  backend is not created at all.
- `K8S_GOAL_NS` optionally narrows goals to one namespace; it does not change
  the incident loop's own `K8S_NS`.
- `K8S_PROTECT` uses the same format and always wins over `K8S_ALLOW`.
- `K8S_GOAL_VERIFY` is the seconds to wait for available replicas after the
  rollback patch.

Restart the healer and verify `/healthz` still reports `execute_enabled` as
expected and `ss -ltnp | grep ':9182'` is loopback-only.

### 8.3 Ops verification

```bash
curl -sS http://127.0.0.1:9190/api/goals/templates | python3 -m json.tool
curl -sS 'http://127.0.0.1:9190/api/goals/targets?template_id=k8s.deployment.rollback.v1' \
  | python3 -m json.tool
```

The template list includes `k8s.deployment.rollback.v1`, and the targets
response has `target_kind=k8s_deployment` with rows containing `revision`,
`previous_revision`, `status`, `replicas`, `available`, `images`,
`previous_images`, `allowed`, and `protected`. An empty `K8S_ALLOW` shows
`error=k8s_disabled`; a cluster/API failure shows `error=k8s_unavailable`.

### 8.4 Dry-run rehearsal (`DRY_RUN=1`)

Use a lab Deployment that is currently `degraded` and has a previous revision
with different images. Never rehearse on a `K8S_PROTECT` target or a production
workload.

1. Select `k8s.deployment.rollback.v1`, the lab Deployment, a reason, and
   `expected_effect=available`. Preview must show `rollout_undo`, risk `high`,
   `generated_by=rules`, the revision transition, and the image transition.
2. Create the goal, copy the one-time code, and approve as a different approver
   (or the opted-in single identity). High-risk approval requires the typed
   phrase `SETUJU rollout_undo <namespace>/<deployment>` unless a high-risk
   passphrase is configured.
3. Execute. Confirm the goal reaches `succeeded`, the journal run has
   `dry_run=true`, `from_revision`/`to_revision` are present, and the Deployment
   was **not** patched.
4. Confirm `decisions.jsonl` has one entry with `sumber="goal"`,
   `jenis_target="deployment"`, the plan id/hash, and the approver name; the
   guest `insiden_24j` must not change.
5. Replay the same execute request: the healer returns the old run, no second
   action.
6. Remove the Deployment from `K8S_ALLOW` (restart healer) and preview again:
   the preview is `404 target_not_allowed`. If a plan was approved before the
   change, execute must end `failed` with `target_not_allowed`.
7. Add the Deployment to `K8S_PROTECT`: preview is `blocked` with
   `protected_target`, and a forced plan must be rejected by the healer with
   `403 protected_target`.
8. Confirm a Deployment whose `revision == previous_revision` or whose status is
   `scaled-to-zero` yields `escalate` (not executable).

### 8.5 One real rollback (`DRY_RUN=0`)

1. Set `DRY_RUN=0` on the healer and restart it. This also affects guest goals;
   keep the Phase 2 safety checks in mind.
2. Break the lab Deployment intentionally (deploy a bad image) so it is
   `degraded` with a healthy previous revision.
3. Run preview → approve → execute. The run result should show
   `from_revision`, `to_revision`, `images`, `new_revision`, and
   `recovered=true`; the Deployment returns to available replicas.
4. If the result is `verify_timeout`, the patch was applied but replicas did not
   recover within `K8S_GOAL_VERIFY`. Inspect the Deployment before creating a new
   goal; do not blindly re-execute.
5. Kill the healer between claim and finish: after restart the stale claim must
   become `unknown`. Use **Reconcile**; never re-execute.

### 8.6 Rollback / disable Phase 3A

- Set `K8S_ALLOW=` (empty) on the healer and restart: the k8s target list
  returns `error=k8s_disabled` and previews answer `404 target_not_allowed`
  because no Deployment is listable. Guest goals and the incident loop continue
  to work.
- Setting `GOALS_EXECUTE_ENABLED=false` on Ops or `GOALS_EXECUTE=0` on the
  healer disables all execution, including k8s, exactly as in section 7.6.
- Never delete `goal_runs.jsonl`: it is shared by guest and Deployment plans and
  is the replay-protection record for both.
- Rotating `CONTROL_KEY` works the same way; there is no separate k8s key.
