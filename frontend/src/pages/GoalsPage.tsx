import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { GoalPlanView } from "../components/GoalPlan";
import { Icon } from "../components/Icon";
import { CopyButton, Empty, ErrorState, PageHead, Panel, Pill } from "../components/ui";
import { api, errorMessage } from "../data/api";
import { dateTimeOf } from "../data/format";
import {
  goalBlockedLabel,
  goalRiskTone,
  goalStatusLabel,
  goalStatusTone,
  remainingLabel
} from "../data/goals";
import type {
  GoalActionResponse,
  GoalAuditResponse,
  GoalCreated,
  GoalListResponse,
  GoalPreviewResponse,
  GoalTemplate,
  GoalTemplatesResponse,
  GoalView,
  GuestsResponse,
  KnobsResponse
} from "../data/types";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../state/auth";
import { useRefresh } from "../state/refresh";
import { useToast } from "../state/toast";

type VariableValue = string | boolean;
type VariableValues = Record<string, VariableValue>;
type Busy = "preview" | "create" | "approve" | "reject" | "cancel" | null;

const MAX_GOAL_CHARS = 1000;

const APPROVAL_MODE_LABEL: Record<string, string> = {
  two_person: "two-person",
  self_allowed: "self-approval allowed",
  password_single_person: "single person (password mode)"
};

function newIdempotencyKey(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function variablesFor(template: GoalTemplate | null, previous: VariableValues): VariableValues {
  if (!template) return {};
  const next: VariableValues = {};
  for (const spec of template.variables) {
    const existing = previous[spec.name];
    if (spec.type === "boolean") {
      next[spec.name] = typeof existing === "boolean" ? existing : Boolean(spec.default);
    } else if (spec.type === "enum") {
      next[spec.name] =
        typeof existing === "string" && spec.enum.includes(existing)
          ? existing
          : typeof spec.default === "string"
            ? spec.default
            : spec.enum[0] ?? "";
    } else {
      next[spec.name] =
        typeof existing === "string"
          ? existing
          : typeof spec.default === "string"
            ? spec.default
            : "";
    }
  }
  return next;
}

function missingVariables(template: GoalTemplate | null, values: VariableValues): string[] {
  if (!template) return [];
  return template.variables
    .filter((spec) => {
      if (!spec.required) return false;
      const value = values[spec.name];
      return typeof value === "string" ? !value.trim() : value === undefined;
    })
    .map((spec) => spec.name);
}

function approvalModeLabel(value: string): string {
  return APPROVAL_MODE_LABEL[value] ?? (value || "—");
}

function goalWindow(goal: GoalView, now: number): string {
  if (goal.status === "pending_approval") return remainingLabel(goal.expires_at, now);
  if (goal.status === "approved") return remainingLabel(goal.execute_before, now);
  return "—";
}

export function GoalsPage() {
  const { info } = useAuth();
  const { refresh } = useRefresh();
  const toast = useToast();
  const goalsEnabled = Boolean(info?.features?.goals);
  const isApprover = Boolean(info?.can_approve);

  const templatesApi = useApi<GoalTemplatesResponse>(
    goalsEnabled ? "/api/goals/templates" : null,
    120_000
  );
  const guestsApi = useApi<GuestsResponse>("/api/guests", 30_000);
  const knobsApi = useApi<KnobsResponse>(goalsEnabled ? "/api/knobs" : null, 30_000);
  const [historyVersion, setHistoryVersion] = useState(0);
  const historyApi = useApi<GoalListResponse>(
    goalsEnabled ? `/api/goals?limit=25&v=${historyVersion}` : null,
    20_000
  );

  const templates = useMemo(
    () => templatesApi.data?.templates ?? [],
    [templatesApi.data]
  );
  const guests = useMemo(
    () => [...(guestsApi.data?.guests.guests ?? [])].sort((a, b) => a.vmid - b.vmid),
    [guestsApi.data]
  );
  const protectIds = useMemo(
    () => new Set(knobsApi.data?.knobs.PROTECT ?? []),
    [knobsApi.data]
  );
  const autoIds = useMemo(
    () => new Set(knobsApi.data?.knobs.AUTO_IDS ?? []),
    [knobsApi.data]
  );

  const [templateId, setTemplateId] = useState("");
  const [targetVmid, setTargetVmid] = useState("");
  const [goal, setGoal] = useState("");
  const [variables, setVariables] = useState<VariableValues>({});
  const [preview, setPreview] = useState<GoalPreviewResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [idempotencyKey, setIdempotencyKey] = useState("");
  const [created, setCreated] = useState<GoalCreated | null>(null);
  const [activeGoal, setActiveGoal] = useState<GoalView | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Busy>(null);

  const [approvalCode, setApprovalCode] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [cancelReason, setCancelReason] = useState("");

  const [drawerGoal, setDrawerGoal] = useState<GoalView | null>(null);
  const [audit, setAudit] = useState<GoalAuditResponse | null>(null);
  const [auditError, setAuditError] = useState<string | null>(null);
  const [auditLoading, setAuditLoading] = useState(false);

  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!templateId && templates.length) setTemplateId(templates[0].id);
  }, [templateId, templates]);

  const template = templates.find((item) => item.id === templateId) ?? templates[0] ?? null;
  const templateKey = template ? `${template.id}:${template.version}` : "";

  useEffect(() => {
    setVariables((previous) => variablesFor(template, previous));
    // templateKey stands in for the template identity; re-fetching identical
    // templates must not wipe the operator's values.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templateKey]);

  useEffect(() => {
    setPreview(null);
    setPreviewError(null);
    setIdempotencyKey("");
  }, [templateKey, targetVmid, goal, variables]);

  const selectedGuest = guests.find((guest) => String(guest.vmid) === targetVmid) ?? null;
  const selectedProtected = selectedGuest ? protectIds.has(selectedGuest.vmid) : false;
  const selectedAuto = selectedGuest ? autoIds.has(selectedGuest.vmid) : false;

  const drawerId = drawerGoal?.id ?? "";
  useEffect(() => {
    if (!drawerId) {
      setAudit(null);
      setAuditError(null);
      setAuditLoading(false);
      return;
    }
    let alive = true;
    setAudit(null);
    setAuditError(null);
    setAuditLoading(true);
    api
      .get<GoalAuditResponse>(`/api/goals/${encodeURIComponent(drawerId)}/audit`)
      .then((response) => {
        if (alive) setAudit(response);
      })
      .catch((error: unknown) => {
        if (alive) setAuditError(errorMessage(error));
      })
      .finally(() => {
        if (alive) setAuditLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [drawerId]);

  const resetApprovalFields = () => {
    setApprovalCode("");
    setPassphrase("");
    setConfirmation("");
    setConfirmed(false);
    setRejectReason("");
    setCancelReason("");
  };

  const reloadHistory = () => setHistoryVersion((value) => value + 1);

  const runPreview = async (event: FormEvent) => {
    event.preventDefault();
    setPreviewError(null);
    setActionError(null);
    if (!template) {
      setPreviewError("Template belum tersedia dari server.");
      return;
    }
    if (!selectedGuest) {
      setPreviewError("Pilih guest target terlebih dahulu.");
      return;
    }
    const missing = missingVariables(template, variables);
    if (missing.length) {
      setPreviewError(`Variabel wajib belum diisi: ${missing.join(", ")}.`);
      return;
    }

    const payloadVariables: VariableValues = {};
    for (const spec of template.variables) {
      const value = variables[spec.name];
      if (value === undefined) continue;
      payloadVariables[spec.name] = typeof value === "string" ? value.trim() : value;
    }

    setBusy("preview");
    try {
      const response = await api.post<GoalPreviewResponse>("/api/goals/preview", {
        template_id: template.id,
        target: { vmid: selectedGuest.vmid },
        goal: goal.trim(),
        variables: payloadVariables
      });
      setPreview(response);
      setCreated(null);
      setActiveGoal(null);
      setIdempotencyKey(newIdempotencyKey());
      resetApprovalFields();
    } catch (error) {
      setPreviewError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const requestCreate = async () => {
    if (!preview || preview.status !== "ready") return;
    setBusy("create");
    setActionError(null);
    const key = idempotencyKey || newIdempotencyKey();
    setIdempotencyKey(key);
    try {
      const response = await api.post<GoalCreated>("/api/goals", {
        preview_id: preview.preview_id,
        plan_hash: preview.plan_hash,
        idempotency_key: key
      });
      setCreated(response);
      setActiveGoal(response);
      setPreview(null);
      resetApprovalFields();
      reloadHistory();
      toast(
        response.idempotent_replay
          ? "Goal sudah ada — kode lama tidak dapat dipulihkan"
          : "Goal dibuat — simpan kode approval"
      );
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const requirements = activeGoal?.requirements;
  const needsTypedConfirmation = Boolean(
    requirements?.typed_confirmation && !requirements.passphrase_required
  );
  const typedConfirmationOk =
    !needsTypedConfirmation ||
    (requirements?.typed_confirmation ?? "").trim().toUpperCase() ===
      confirmation.trim().toUpperCase();
  const passphraseOk = !requirements?.passphrase_required || passphrase.length > 0;
  const approvalCodeOk = approvalCode.trim().length >= 8;
  const approveDisabled =
    busy !== null ||
    !activeGoal ||
    !activeGoal.plan_hash ||
    !approvalCodeOk ||
    !confirmed ||
    !typedConfirmationOk ||
    !passphraseOk;

  const submitApprove = async (event: FormEvent) => {
    event.preventDefault();
    if (!activeGoal || approveDisabled) return;
    setBusy("approve");
    setActionError(null);
    try {
      const response = await api.post<GoalActionResponse>(
        `/api/goals/${encodeURIComponent(activeGoal.id)}/approve`,
        {
          plan_hash: activeGoal.plan_hash,
          approval_code: approvalCode.trim(),
          confirm: confirmed,
          high_risk_passphrase: passphrase,
          confirmation: confirmation.trim()
        }
      );
      setActiveGoal(response.goal);
      setCreated(null);
      resetApprovalFields();
      reloadHistory();
      toast("Goal disetujui");
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const submitReject = async () => {
    if (!activeGoal) return;
    if (!rejectReason.trim()) {
      setActionError("Alasan reject wajib diisi.");
      return;
    }
    setBusy("reject");
    setActionError(null);
    try {
      const response = await api.post<GoalActionResponse>(
        `/api/goals/${encodeURIComponent(activeGoal.id)}/reject`,
        {
          plan_hash: activeGoal.plan_hash,
          reason: rejectReason.trim()
        }
      );
      setActiveGoal(response.goal);
      setCreated(null);
      resetApprovalFields();
      reloadHistory();
      toast("Goal ditolak");
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  const submitCancel = async () => {
    if (!activeGoal) return;
    if (!cancelReason.trim()) {
      setActionError("Alasan pembatalan wajib diisi.");
      return;
    }
    setBusy("cancel");
    setActionError(null);
    try {
      const response = await api.post<GoalActionResponse>(
        `/api/goals/${encodeURIComponent(activeGoal.id)}/cancel`,
        { reason: cancelReason.trim() }
      );
      setActiveGoal(response.goal);
      setCreated(null);
      resetApprovalFields();
      reloadHistory();
      toast("Goal dibatalkan");
    } catch (error) {
      setActionError(errorMessage(error));
    } finally {
      setBusy(null);
    }
  };

  if (!goalsEnabled) {
    return (
      <>
        <PageHead
          eyebrow="Control · AI goals"
          title="AI Goals"
          sub="Fitur ini hanya tersedia bila GOALS_ENABLED=true dan AUTH_MODE bukan off."
        />
        <Panel title="AI Goals nonaktif" sub="feature flag">
          <Empty>GOALS_ENABLED=false — tidak ada route write, planner, atau approval code.</Empty>
        </Panel>
      </>
    );
  }

  const history = historyApi.data?.goals ?? [];
  const pendingCount = history.filter((item) => item.status === "pending_approval").length;
  const canCancel = Boolean(
    activeGoal &&
      (activeGoal.requested_by_sub === info?.user?.sub || isApprover) &&
      (activeGoal.status === "pending_approval" || activeGoal.status === "approved")
  );
  const activeAction = activeGoal?.plan?.steps?.[0]?.action ?? "—";
  const owner = activeGoal?.requested_by_sub === info?.user?.sub;

  return (
    <>
      <PageHead
        eyebrow={
          historyApi.data
            ? `Control · AI goals · ${history.length} recent · ${pendingCount} pending`
            : "Control · AI goals"
        }
        title="AI Goals"
        sub="Operator memberi goal dan variabel; server membangun plan immutable dari closed action set. AI tidak pernah mengeksekusi — approval manusia dan kode sekali pakai wajib."
        actions={
          <>
            <Pill
              tone={info?.features?.goals_execute ? "coral" : "mint"}
              dot={info?.features?.goals_execute ? "coral" : "mint"}
              style={{ height: 30 }}
            >
              {info?.features?.goals_execute ? "EXECUTE ON" : "execution disabled"}
            </Pill>
            <button type="button" className="btn" onClick={refresh}>
              <Icon name="i-refresh" /> Refresh
            </button>
            <Link className="btn btn-primary" to="/fleet">
              <Icon name="i-layers" /> Fleet
            </Link>
          </>
        }
      />

      {created ? (
        <div className={`banner ${created.approval_code ? "ok" : "crit"} goal-code-banner`} role="status">
          <div className="banner-ico">
            <Icon name={created.approval_code ? "i-key" : "i-alert-triangle"} className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">
              {created.approval_code
                ? "One-time approval code"
                : "Goal ini sudah pernah dibuat — kode tidak bisa dipulihkan"}
            </div>
            <div className="banner-sub">
              {created.approval_code ? (
                <>
                  <code className="goal-code">{created.approval_code}</code>
                  <span>·</span>
                  <span>Tampil sekali di layar ini. Jangan masukkan ke chat, log, atau tiket.</span>
                </>
              ) : (
                <span>Batalkan goal ini lalu buat goal baru jika kode approval hilang.</span>
              )}
            </div>
          </div>
          {created.approval_code ? (
            <div className="banner-actions">
              <CopyButton text={created.approval_code} label="Copy code" />
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="settings">
        <Panel
          title="Compose goal"
          sub="goal + variabel · target ditentukan server dari state healer"
          right={<Pill>{template ? template.name : "template"}</Pill>}
          body
          className="form-panel"
        >
          {templatesApi.error && !templatesApi.data ? (
            <ErrorState message={templatesApi.error} onRetry={refresh} />
          ) : null}

          <form className="goal-form" onSubmit={runPreview}>
            <div className="form-row">
              <div className="field">
                <label htmlFor="goal-template">Template</label>
                <select
                  className="select"
                  id="goal-template"
                  value={template?.id ?? ""}
                  onChange={(event) => {
                    setTemplateId(event.target.value);
                    setTargetVmid("");
                  }}
                  disabled={!templates.length}
                >
                  {templates.length ? (
                    templates.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name} · v{item.version}
                      </option>
                    ))
                  ) : (
                    <option value="">memuat template…</option>
                  )}
                </select>
                <span className="hint">{template?.description ?? "Template statis dari server."}</span>
              </div>

              <div className="field">
                <label htmlFor="goal-target">Target guest</label>
                <select
                  className="select"
                  id="goal-target"
                  value={targetVmid}
                  onChange={(event) => setTargetVmid(event.target.value)}
                  disabled={!guests.length}
                >
                  <option value="">{guests.length ? "Pilih guest…" : "memuat guest…"}</option>
                  {guests.map((guest) => (
                    <option key={guest.vmid} value={guest.vmid}>
                      #{guest.vmid} · {guest.name || "guest"} · {guest.node} · {guest.status}
                      {protectIds.has(guest.vmid) ? " · PROTECT" : autoIds.has(guest.vmid) ? " · AUTO" : ""}
                    </option>
                  ))}
                </select>
                <span className="hint">
                  {selectedGuest
                    ? `${selectedGuest.node} · ${selectedGuest.status}${
                        selectedProtected ? " · PROTECT (preview akan diblokir)" : selectedAuto ? " · AUTO_IDS" : " · non-AUTO (high risk)"
                      }`
                    : "Target tidak bisa diubah oleh AI; server me-resolve node dan jenis guest."}
                </span>
              </div>
            </div>

            <div className="field">
              <label htmlFor="goal-text">
                Goal <span className="hint">(opsional, maks {MAX_GOAL_CHARS} karakter)</span>
              </label>
              <textarea
                className="textarea"
                id="goal-text"
                rows={4}
                maxLength={MAX_GOAL_CHARS}
                value={goal}
                onChange={(event) => setGoal(event.target.value)}
                placeholder="mis. pulihkan web01 setelah maintenance selesai; jangan reset kalau data belum sinkron."
              />
              <div className="goal-char-count">
                <span className="hint">Teks ini adalah data untuk AI, bukan perintah shell atau PromQL.</span>
                <span className="mono">
                  {goal.length}/{MAX_GOAL_CHARS}
                </span>
              </div>
            </div>

            <div className="goal-vars">
              {template?.variables.map((spec) => {
                const value = variables[spec.name];
                const label = spec.name.replaceAll("_", " ");
                if (spec.type === "boolean") {
                  return (
                    <div className="field goal-check-field" key={spec.name}>
                      <label className="checkline" htmlFor={`goal-var-${spec.name}`}>
                        <input
                          id={`goal-var-${spec.name}`}
                          type="checkbox"
                          checked={value === true}
                          onChange={(event) =>
                            setVariables((previous) => ({
                              ...previous,
                              [spec.name]: event.target.checked
                            }))
                          }
                        />
                        <span>
                          {label}
                          {spec.required ? " *" : ""}
                        </span>
                      </label>
                      {spec.description ? <span className="hint">{spec.description}</span> : null}
                    </div>
                  );
                }
                if (spec.type === "enum") {
                  return (
                    <div className="field" key={spec.name}>
                      <label htmlFor={`goal-var-${spec.name}`}>
                        {label}
                        {spec.required ? " *" : ""}
                      </label>
                      <select
                        className="select"
                        id={`goal-var-${spec.name}`}
                        value={typeof value === "string" ? value : ""}
                        onChange={(event) =>
                          setVariables((previous) => ({
                            ...previous,
                            [spec.name]: event.target.value
                          }))
                        }
                      >
                        {spec.enum.map((option) => (
                          <option key={option} value={option}>
                            {option}
                          </option>
                        ))}
                      </select>
                      {spec.description ? <span className="hint">{spec.description}</span> : null}
                    </div>
                  );
                }
                return (
                  <div className="field" key={spec.name}>
                    <label htmlFor={`goal-var-${spec.name}`}>
                      {label}
                      {spec.required ? " *" : ""}
                    </label>
                    <input
                      className="input"
                      id={`goal-var-${spec.name}`}
                      value={typeof value === "string" ? value : ""}
                      maxLength={spec.max_length ?? undefined}
                      onChange={(event) =>
                        setVariables((previous) => ({
                          ...previous,
                          [spec.name]: event.target.value
                        }))
                      }
                    />
                    {spec.description ? <span className="hint">{spec.description}</span> : null}
                  </div>
                );
              })}
            </div>

            <div className="ro-note">
              <Icon name="i-shield" className="icon sm" />
              <span>
                AI hanya boleh memilih <b>start</b>, <b>resume</b>, <b>reset</b>, <b>noop</b>, atau{" "}
                <b>escalate</b>. Tidak ada shell, SSH, URL, atau PromQL dari input ini. PROTECT selalu
                menang.
              </span>
            </div>

            {previewError ? (
              <div className="auth-error" role="alert">
                <Icon name="i-alert-triangle" className="icon sm" /> {previewError}
              </div>
            ) : null}

            <div className="goal-actions">
              <button
                className="btn btn-primary"
                type="submit"
                disabled={busy !== null || !template || !selectedGuest}
              >
                {busy === "preview" ? "Menyusun plan…" : "Preview plan"} <Icon name="i-arrow-right" />
              </button>
              <span className="hint">
                Preview TTL singkat; create me-recheck state healer sebelum plan disimpan.
              </span>
            </div>
          </form>

          {guestsApi.error && !guestsApi.data ? (
            <div className="ro-note">
              <Icon name="i-alert-triangle" className="icon sm" />
              <span>Guest list gagal dimuat: {guestsApi.error}</span>
            </div>
          ) : null}
        </Panel>

        <Panel
          title={activeGoal ? "Active goal" : "Plan preview"}
          sub={
            activeGoal
              ? `${activeGoal.id.slice(0, 8)} · ${goalStatusLabel(activeGoal.status)}`
              : preview
                ? `${preview.status} · plan belum disimpan`
                : "compose → preview → approval"
          }
          right={
            activeGoal ? (
              <Pill tone={goalStatusTone(activeGoal.status)} dot={goalStatusTone(activeGoal.status)}>
                {goalStatusLabel(activeGoal.status)}
              </Pill>
            ) : preview ? (
              <Pill tone={preview.status === "ready" ? "mint" : preview.status === "blocked" ? "coral" : "amber"}>
                {preview.status}
              </Pill>
            ) : (
              <Pill>server-validated</Pill>
            )
          }
          body
        >
          {activeGoal ? (
            <div className="goal-active">
              <div className="goal-active-top">
                <span className="tiny dim">
                  {activeGoal.status === "pending_approval"
                    ? `approval window · ${remainingLabel(activeGoal.expires_at, now)}`
                    : activeGoal.status === "approved"
                      ? `execute before · ${remainingLabel(activeGoal.execute_before, now)}`
                      : `updated ${dateTimeOf(activeGoal.updated_at)}`}
                </span>
                <span className="right tiny dim">{activeAction}</span>
              </div>

              <GoalPlanView
                plan={activeGoal.plan}
                planHash={activeGoal.plan_hash}
                warnings={activeGoal.warnings}
              />

              <div className="kv goal-kv">
                <div>
                  <div className="k">Requested by</div>
                  <div className="v">{activeGoal.requested_by || "—"}</div>
                </div>
                <div>
                  <div className="k">Requested at</div>
                  <div className="v">{dateTimeOf(activeGoal.requested_at)}</div>
                </div>
                <div>
                  <div className="k">Approval mode</div>
                  <div className="v">{approvalModeLabel(activeGoal.approval_mode)}</div>
                </div>
                <div>
                  <div className="k">Approved by</div>
                  <div className="v">{activeGoal.approved_by || "—"}</div>
                </div>
              </div>

              {activeGoal.status === "pending_approval" ? (
                activeGoal.can_approve ? (
                  <form className="goal-approval" onSubmit={submitApprove}>
                    {info?.features?.password_single_person ? (
                      <div className="ro-note">
                        <Icon name="i-alert-triangle" className="icon sm" />
                        <span>
                          Password mode: approval ini <b>single-person</b>. Untuk separation of duties,
                          gunakan OIDC dengan dua akun approver.
                        </span>
                      </div>
                    ) : null}
                    {activeGoal.high_risk ? (
                      <div className="ro-note">
                        <Icon name="i-alert-triangle" className="icon sm" />
                        <span>
                          High risk: {requirements?.passphrase_required
                            ? "passphrase high-risk wajib diisi."
                            : `ketik konfirmasi persis seperti yang diminta.`}
                        </span>
                      </div>
                    ) : null}

                    <div className="field">
                      <label htmlFor="approval-code">Approval code</label>
                      <div className="input-wrap">
                        <Icon name="i-key" />
                        <input
                          className="input mono"
                          id="approval-code"
                          value={approvalCode}
                          onChange={(event) => setApprovalCode(event.target.value.toUpperCase())}
                          autoComplete="one-time-code"
                          maxLength={32}
                          placeholder="12 karakter"
                        />
                      </div>
                      <span className="hint">Kode dari banner setelah create; hanya berlaku sekali.</span>
                    </div>

                    {requirements?.passphrase_required ? (
                      <div className="field">
                        <label htmlFor="approval-passphrase">High-risk passphrase</label>
                        <input
                          className="input"
                          id="approval-passphrase"
                          type="password"
                          value={passphrase}
                          onChange={(event) => setPassphrase(event.target.value)}
                          autoComplete="off"
                          maxLength={256}
                        />
                      </div>
                    ) : null}

                    {needsTypedConfirmation ? (
                      <div className="field">
                        <label htmlFor="approval-confirmation">Typed confirmation</label>
                        <input
                          className="input mono"
                          id="approval-confirmation"
                          value={confirmation}
                          onChange={(event) => setConfirmation(event.target.value)}
                          placeholder={requirements?.typed_confirmation}
                          maxLength={128}
                        />
                        <span className="hint">
                          Ketik <code>{requirements?.typed_confirmation}</code> untuk aksi high risk.
                        </span>
                      </div>
                    ) : null}

                    <div className="field">
                      <label htmlFor="reject-reason">Reject reason</label>
                      <input
                        className="input"
                        id="reject-reason"
                        value={rejectReason}
                        onChange={(event) => setRejectReason(event.target.value)}
                        maxLength={300}
                        placeholder="Wajib bila menolak goal"
                      />
                    </div>

                    <label className="checkline">
                      <input
                        type="checkbox"
                        checked={confirmed}
                        onChange={(event) => setConfirmed(event.target.checked)}
                      />
                      <span>Saya sudah meninjau target, aksi, risk, rationale, dan evidence.</span>
                    </label>

                    {actionError ? (
                      <div className="auth-error" role="alert">
                        <Icon name="i-alert-triangle" className="icon sm" /> {actionError}
                      </div>
                    ) : null}

                    <div className="goal-actions">
                      <button className="btn btn-primary" type="submit" disabled={approveDisabled}>
                        <Icon name="i-shield" /> {busy === "approve" ? "Menyetujui…" : "Approve"}
                      </button>
                      <button
                        className="btn"
                        type="button"
                        onClick={() => void submitReject()}
                        disabled={busy !== null || !rejectReason.trim()}
                      >
                        <Icon name="i-x" /> {busy === "reject" ? "Menolak…" : "Reject"}
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="ro-note">
                    <Icon name="i-clock" className="icon sm" />
                    <span>
                      {owner && !isApprover
                        ? "Menunggu approver lain. Approver harus memakai akun berbeda; self-approval tidak diizinkan."
                        : owner
                          ? "Menunggu approver lain (self-approval tidak diizinkan)."
                          : "Menunggu approver."}
                    </span>
                  </div>
                )
              ) : null}

              {activeGoal.status === "approved" ? (
                <div className="ro-note">
                  <Icon name="i-check-circle" className="icon sm" />
                  <span>
                    Disetujui oleh <b>{activeGoal.approved_by || "—"}</b> pada{" "}
                    {dateTimeOf(activeGoal.approved_at)}.{" "}
                    {activeGoal.execution_enabled
                      ? "Eksekusi adalah klik kedua yang terpisah dan belum tersedia di UI fase ini."
                      : "GOALS_EXECUTE_ENABLED=false — eksekusi tidak tersedia; tidak ada aksi yang dikirim ke healer."}
                  </span>
                </div>
              ) : null}

              {activeGoal.status === "rejected" ||
              activeGoal.status === "cancelled" ||
              activeGoal.status === "expired" ||
              activeGoal.status === "failed" ? (
                <div className="ro-note">
                  <Icon name="i-info" className="icon sm" />
                  <span>
                    {activeGoal.status === "rejected"
                      ? `Ditolak oleh ${activeGoal.rejected_by || "—"}: ${
                          activeGoal.reject_reason || "tanpa alasan"
                        }`
                      : activeGoal.status === "cancelled"
                        ? `Dibatalkan: ${activeGoal.reject_reason || "tanpa alasan"}`
                        : activeGoal.status === "expired"
                          ? "Goal kedaluwarsa sebelum disetujui / dieksekusi."
                          : `Goal gagal: ${activeGoal.error || "tanpa detail"}`}
                  </span>
                </div>
              ) : null}

              {actionError && !activeGoal.can_approve ? (
                <div className="auth-error" role="alert">
                  <Icon name="i-alert-triangle" className="icon sm" /> {actionError}
                </div>
              ) : null}

              {canCancel ? (
                <div className="goal-cancel">
                  <div className="field">
                    <label htmlFor="cancel-reason">Cancellation reason</label>
                    <input
                      className="input"
                      id="cancel-reason"
                      value={cancelReason}
                      onChange={(event) => setCancelReason(event.target.value)}
                      maxLength={300}
                      placeholder="Wajib untuk membatalkan goal"
                    />
                  </div>
                  <button
                    type="button"
                    className="btn"
                    onClick={() => void submitCancel()}
                    disabled={busy !== null || !cancelReason.trim()}
                  >
                    <Icon name="i-x" /> {busy === "cancel" ? "Membatalkan…" : "Cancel goal"}
                  </button>
                </div>
              ) : null}
            </div>
          ) : preview ? (
            <div className="goal-preview">
              <div className="goal-active-top">
                <span className="tiny dim">
                  {preview.status === "ready"
                    ? `preview ${remainingLabel(preview.expires_at, now)}`
                    : preview.status}
                </span>
                <span className="right tiny dim">
                  {preview.plan?.steps?.[0]?.action ?? "—"}
                </span>
              </div>

              {preview.status === "blocked" ? (
                <div className="goal-blocked" role="alert">
                  <Icon name="i-alert-triangle" className="icon sm" />
                  <span>
                    {goalBlockedLabel(preview.blocked_reason)}
                    {preview.blocked_reason ? (
                      <span className="mono"> · {preview.blocked_reason}</span>
                    ) : null}
                  </span>
                </div>
              ) : null}

              <GoalPlanView
                plan={preview.plan}
                planHash={preview.plan_hash}
                warnings={preview.warnings}
              />

              {preview.missing.length ? (
                <div className="ro-note">
                  <Icon name="i-info" className="icon sm" />
                  <span>Input yang masih kurang: {preview.missing.join(", ")}</span>
                </div>
              ) : null}

              {actionError ? (
                <div className="auth-error" role="alert">
                  <Icon name="i-alert-triangle" className="icon sm" /> {actionError}
                </div>
              ) : null}

              <div className="goal-actions">
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={() => void requestCreate()}
                  disabled={busy !== null || preview.status !== "ready"}
                >
                  <Icon name="i-lock" /> {busy === "create" ? "Menyimpan…" : "Request approval"}
                </button>
                <span className="hint">
                  {preview.status === "ready"
                    ? "Server menyimpan plan + hash, lalu membuat kode approval sekali pakai."
                    : "Plan ini tidak bisa diajukan. Ubah input lalu preview ulang."}
                </span>
              </div>
            </div>
          ) : (
            <div className="goal-empty">
              <span className="agent-avatar violet">
                <Icon name="i-target" />
              </span>
              <div>
                <div className="agent-name">Belum ada plan</div>
                <div className="agent-sub">pilih guest, isi variabel, lalu preview</div>
              </div>
            </div>
          )}
        </Panel>
      </div>

      <Panel
        className="mt-14"
        title="Goal history"
        sub={isApprover ? "approver view · semua goal" : "hanya goal milik akun ini"}
        right={<Pill>{history.length} recent</Pill>}
      >
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Guest</th>
                <th>Action</th>
                <th>Requested by</th>
                <th>Created</th>
                <th>Window</th>
                <th>Plan</th>
              </tr>
            </thead>
            <tbody>
              {historyApi.loading && !historyApi.data ? (
                <tr>
                  <td colSpan={8} className="empty">
                    <span className="spinner" aria-hidden="true" /> memuat goal…
                  </td>
                </tr>
              ) : history.length === 0 ? (
                <tr>
                  <td colSpan={8} className="empty">
                    Belum ada goal. Compose plan pertama di atas.
                  </td>
                </tr>
              ) : (
                history.map((item, index) => {
                  const step = item.plan?.steps?.[0];
                  return (
                    <tr
                      key={item.id}
                      tabIndex={0}
                      onClick={() => setDrawerGoal(item)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") setDrawerGoal(item);
                      }}
                    >
                      <td className="cell-id">{String(index + 1).padStart(2, "0")}</td>
                      <td>
                        <Pill tone={goalStatusTone(item.status)} dot={goalStatusTone(item.status)}>
                          {goalStatusLabel(item.status)}
                        </Pill>
                      </td>
                      <td>
                        <div className="agent-name">
                          {item.target?.name || item.plan?.target?.name || "guest"}
                        </div>
                        <div className="agent-sub">
                          #{item.target?.vmid ?? item.plan?.target?.vmid ?? "—"} ·{" "}
                          {item.target?.node ?? item.plan?.target?.node ?? "—"}
                        </div>
                      </td>
                      <td>
                        <Pill tone={goalRiskTone(step?.risk ?? "low")}>{step?.action ?? "—"}</Pill>
                      </td>
                      <td className="cell-task">{item.requested_by || item.requested_by_sub || "—"}</td>
                      <td className="cell-time">{dateTimeOf(item.created_at)}</td>
                      <td className="cell-time">{goalWindow(item, now)}</td>
                      <td>
                        <span className="mono goal-hash-cell" title={item.plan_hash}>
                          {item.plan_hash ? `${item.plan_hash.slice(0, 12)}…` : "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <div className="table-foot">
          <span>{history.length} goal terakhir · limit 25</span>
          <span style={{ color: "var(--faint)" }}>·</span>
          <span>{isApprover ? "approver dapat melihat semua requester" : "requester melihat miliknya"}</span>
          <span className="right">
            {historyApi.error ? (
              <span style={{ color: "var(--coral)" }}>{historyApi.error}</span>
            ) : (
              <span>refresh tiap 20 s</span>
            )}
          </span>
        </div>
      </Panel>

      <div
        className={`scrim${drawerGoal ? " open" : ""}`}
        onClick={() => setDrawerGoal(null)}
      />
      <aside
        className={`drawer${drawerGoal ? " open" : ""}`}
        aria-label="Goal detail"
        aria-hidden={!drawerGoal}
      >
        <div className="drawer-head">
          <div>
            <div className="title">Goal detail</div>
            <div className="sub">{drawerGoal ? drawerGoal.id.slice(0, 12) : "—"}</div>
          </div>
          <button
            type="button"
            className="btn-icon drawer-close"
            onClick={() => setDrawerGoal(null)}
            aria-label="Close"
          >
            <Icon name="i-x" />
          </button>
        </div>
        <div className="drawer-body">
          {drawerGoal ? (
            <>
              <div className="drawer-hero">
                <span className="agent-avatar violet">
                  <Icon name="i-target" />
                </span>
                <div>
                  <div className="name">
                    {drawerGoal.target?.name || drawerGoal.plan?.target?.name || "goal"}
                  </div>
                  <div className="sub">
                    #{drawerGoal.target?.vmid ?? drawerGoal.plan?.target?.vmid ?? "—"} ·{" "}
                    {drawerGoal.template_id}
                  </div>
                </div>
                <Pill
                  tone={goalStatusTone(drawerGoal.status)}
                  dot={goalStatusTone(drawerGoal.status)}
                  style={{ marginLeft: "auto" }}
                >
                  {goalStatusLabel(drawerGoal.status)}
                </Pill>
              </div>

              <GoalPlanView
                plan={drawerGoal.plan}
                planHash={drawerGoal.plan_hash}
                warnings={drawerGoal.warnings}
              />

              <div className="kv">
                <div>
                  <div className="k">Requested by</div>
                  <div className="v">{drawerGoal.requested_by || "—"}</div>
                </div>
                <div>
                  <div className="k">Requested at</div>
                  <div className="v">{dateTimeOf(drawerGoal.requested_at)}</div>
                </div>
                <div>
                  <div className="k">Approved by</div>
                  <div className="v">{drawerGoal.approved_by || "—"}</div>
                </div>
                <div>
                  <div className="k">Approved at</div>
                  <div className="v">{dateTimeOf(drawerGoal.approved_at)}</div>
                </div>
                <div>
                  <div className="k">Approval mode</div>
                  <div className="v">{approvalModeLabel(drawerGoal.approval_mode)}</div>
                </div>
                <div>
                  <div className="k">Execution</div>
                  <div className="v" style={{ fontSize: 11 }}>
                    {drawerGoal.execution_enabled ? drawerGoal.status : "disabled"}
                  </div>
                </div>
              </div>

              {drawerGoal.reject_reason ? (
                <div className="ro-note">
                  <Icon name="i-info" className="icon sm" />
                  <span>{drawerGoal.reject_reason}</span>
                </div>
              ) : null}

              <div>
                <div className="sect-title">Audit trail</div>
                {auditLoading ? (
                  <div className="empty">
                    <span className="spinner" aria-hidden="true" /> memuat audit…
                  </div>
                ) : auditError ? (
                  <div className="ro-note">
                    <Icon name="i-alert-triangle" className="icon sm" />
                    <span>{auditError}</span>
                  </div>
                ) : audit && audit.events.length ? (
                  <div className="event-list">
                    {audit.events.map((entry, index) => (
                      <div className="event" key={`${entry.ts}-${index}`}>
                        <div className="event-rail">
                          <span
                            className={`event-dot ${
                              entry.event.includes("failed") || entry.event.includes("blocked")
                                ? "coral"
                                : entry.event.includes("approved")
                                  ? "mint"
                                  : entry.event.includes("created")
                                    ? "blue"
                                    : "amber"
                            }`}
                          />
                        </div>
                        <div className="event-body">
                          <div className="t">{entry.event}</div>
                          <div className="m">
                            {dateTimeOf(entry.ts)} · {entry.actor || entry.actor_sub || "—"}
                            {entry.actor_method ? ` · ${entry.actor_method}` : ""}
                          </div>
                          {Object.keys(entry.detail ?? {}).length ? (
                            <pre className="goal-audit-detail">
                              {JSON.stringify(entry.detail, null, 2)}
                            </pre>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="tiny dim">Belum ada event audit.</div>
                )}
              </div>

              <details className="json">
                <summary>Raw goal object</summary>
                <pre>{JSON.stringify(drawerGoal, null, 2)}</pre>
              </details>
            </>
          ) : (
            <Empty>Pilih goal dari history.</Empty>
          )}
        </div>
        <div className="drawer-foot">
          {drawerGoal ? (
            <CopyButton
              text={JSON.stringify(audit ?? drawerGoal, null, 2)}
              label="Copy audit"
            />
          ) : null}
          {drawerGoal?.plan_hash ? (
            <CopyButton text={drawerGoal.plan_hash} label="Copy hash" />
          ) : null}
        </div>
      </aside>
    </>
  );
}
