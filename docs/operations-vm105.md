# VM105 operations — AI Goals Phase 1

This checklist deploys and rehearses AI Goals in **Phase 1 only**: preview,
create, approve, reject, cancel, audit. There is no execution path and no call
to the healer control port.

> **Do not enable Phase 2 execution from this document.** The healer
> `/execute` API, HMAC client, replay journal and `EXEC_LOCK` integration do not
> exist yet. `GOALS_EXECUTE_ENABLED` must stay `false` in this release.

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

## 2. Configure Phase 1

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

Check that no execution listener is required for Phase 1:

```bash
# Optional: if the healer Phase 0 control skeleton is enabled, it must be
# health-only. Otherwise nothing should be listening on 9182.
ss -ltnp | grep ':9182' || true
curl -sS http://127.0.0.1:9182/healthz || true
```

Phase 1 Ops must never POST to `:9182`. The only healer traffic is its existing
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
   - Confirm the final status is `approved`, `execute_before` is set, and no
     **Execute** action is offered.
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
7. **No execution**
   - `Execute` is absent/disabled.
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

## 7. Phase 2 gate (not in this release)

Do not set `GOALS_EXECUTE_ENABLED=true` or configure `GOALS_CONTROL_KEY` until
all of the following exist and have been rehearsed:

- healer `goal_control.py` HMAC `/execute` + `/runs/{plan_id}`, loopback
  enforcement, timestamp/replay protection, JSON journal;
- healer re-validation of `PROTECT`, target state, action, cooldown, incident
  conflicts, `GOALS_ALLOW_NON_AUTO`, and rate limits;
- Ops control client with no automatic retry, `dispatching`/`executing`/
  `unknown` reconciliation, and timeout handling;
- `DRY_RUN=1` rehearsal first, then an isolated lab guest with `DRY_RUN=0`;
- proof that duplicate/replayed plans produce one action and that timeouts become
  `unknown` rather than being retried;
- updated audit/runbook and on-call approval procedure.

Until then, any `execute` result is expected to be `409 execution_disabled`.
