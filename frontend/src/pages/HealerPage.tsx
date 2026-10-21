import { Icon } from "../components/Icon";
import { ErrorState, PageHead, Panel, Pill } from "../components/ui";
import { fmtAge, timeOf } from "../data/format";
import type { KnobsResponse, MetricCounter } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../state/auth";
import { useRefresh } from "../state/refresh";
import { useToast } from "../state/toast";

function buildApplyCommands(ssh: string): string {
  return [
    "# 1. edit env runtime (env var, bukan file di repo)",
    `ssh ${ssh} 'sudoedit /etc/proxmox-healer.env'`,
    "",
    "# 2. restart lalu pastikan unit hidup",
    `ssh ${ssh} 'systemctl restart proxmox-healer && systemctl is-active proxmox-healer'`,
    "",
    "# 3. verifikasi knob yang benar-benar aktif",
    "curl -s http://127.0.0.1:9181/api/knobs | jq .",
    "",
    "# 4. lihat baris startup (llm=ya|tidak, auto=[...])",
    `ssh ${ssh} 'journalctl -u proxmox-healer -n 5 --no-pager'`
  ].join("\n");
}

function buildApprovalCommands(ssh: string): string {
  return [
    "# lihat antrean persetujuan (read-only)",
    `ssh ${ssh} 'python3 /opt/proxmox-healer/healer.py --pending'`,
    "",
    "# setujui satu vmid — hanya dari VM105",
    `ssh ${ssh} 'python3 /opt/proxmox-healer/healer.py --approve <vmid>'`
  ].join("\n");
}

function MetricRows({ items }: { items: MetricCounter[] }) {
  if (!items.length) return <div className="tiny dim">Belum ada series.</div>;
  return (
    <>
      {items.map((item, index) => (
        <div
          key={`${index}-${Object.entries(item.labels)
            .map(([key, value]) => `${key}=${value}`)
            .join("|")}`}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 0",
            borderTop: index ? "1px solid var(--line)" : undefined
          }}
        >
          <span className="mono" style={{ fontSize: 11 }}>
            {Object.entries(item.labels)
              .map(([key, value]) => `${key}=${value}`)
              .join(" · ") || "(tanpa label)"}
          </span>
          <span style={{ marginLeft: "auto", fontWeight: 600, fontSize: 12 }}>{item.value}</span>
        </div>
      ))}
    </>
  );
}

export function HealerPage() {
  const { data, error, loading } = useApi<KnobsResponse>("/api/knobs", 30_000);
  const { info } = useAuth();
  const { refresh } = useRefresh();
  const toast = useToast();
  const plane = info?.plane;
  const goals = Boolean(info?.features?.goals);
  const goalsExecute = Boolean(info?.features?.goals_execute);
  const ssh = plane ? `${plane.ssh_user}@${plane.host}` : "root@host";
  const applyCommands = buildApplyCommands(ssh);
  const approvalCommands = buildApprovalCommands(ssh);
  const knobs = data?.knobs ?? {};
  const dry = Boolean(knobs.DRY_RUN);
  const autoIds = knobs.AUTO_IDS ?? [];
  const protect = knobs.PROTECT ?? [];
  const minorActions = knobs.MINOR_ACTIONS ?? [];
  const k8sNs = knobs.K8S_NS ?? [];
  const nodes = Object.entries(knobs.NODES ?? {});
  const metrics = data?.metrics;
  const lastDecision = data?.last_decision;
  const pending = data?.pending ?? [];
  const awaiting = pending.filter((item) => !item.approved);
  const classifier = data?.classifier;
  const engine = data?.engine;
  const goalCount = data?.summary.goal_24h;
  const links = data?.links ?? {};
  const actionTotals = metrics?.action_totals ?? [];
  const incidentTotals = metrics?.incident_totals ?? [];
  const approvalTotals = metrics?.approval_totals ?? [];
  const k8sActionTotals = metrics?.k8s_action_totals ?? [];
  const k8sEscalationTotals = metrics?.k8s_escalation_totals ?? [];
  const nodeFailures = metrics?.node_failures ?? [];

  return (
    <>
      <PageHead
        eyebrow={goals ? "Control · knob runtime · incident approval" : "Control · knob runtime · read-only"}
        title="Healer"
        sub={
          goals
            ? "Konfigurasi runtime, antrean persetujuan insiden, dan metrik healer. Approval insiden tetap lewat SSH/CLI; aksi goal lewat halaman AI Goals dengan approval terpisah."
            : "Konfigurasi runtime, antrean persetujuan, dan metrik healer. Read-only — perubahan dan approval lewat SSH/CLI."
        }
        actions={
          <>
            <Pill tone={dry ? "amber" : "mint"} dot={dry ? "amber" : "mint"} style={{ height: 30 }}>
              {dry ? "DRY_RUN" : "aksi aktif"}
            </Pill>
            {links.healer_ui ? (
              <a className="btn" href={links.healer_ui} target="_blank" rel="noreferrer">
                <Icon name="i-external" /> Healer UI
              </a>
            ) : null}
            <button type="button" className="btn" onClick={refresh}>
              <Icon name="i-refresh" /> Refresh
            </button>
            <a className="btn btn-primary" href="#apply">
              <Icon name="i-terminal" /> Apply via SSH
            </a>
          </>
        }
      />

      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      <div className="settings">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Panel
            title="Persetujuan manusia"
            sub="aksi yang butuh izin · /api/pending"
            right={
              <Pill tone={awaiting.length ? "amber" : "mint"} dot={awaiting.length ? "amber" : "mint"}>
                {awaiting.length ? `${awaiting.length} menunggu` : "tidak ada"}
              </Pill>
            }
            body
          >
            {loading && !data ? (
              <div className="empty">
                <span className="spinner" aria-hidden="true" /> memuat antrean…
              </div>
            ) : !data?.pending_ok ? (
              <div className="ro-note">
                <Icon name="i-alert-triangle" className="icon sm" />
                <span>/api/pending tidak terjangkau — antrean tidak bisa dipastikan.</span>
              </div>
            ) : pending.length === 0 ? (
              <div className="empty">Tidak ada aksi menunggu persetujuan.</div>
            ) : (
              <div className="event-list">
                {pending.map((item) => (
                  <div className="event" key={`${item.vmid}-${item.diminta}`}>
                    <div className="event-rail">
                      <span className={`event-dot ${item.approved ? "mint" : "amber"}`} />
                    </div>
                    <div className="event-body">
                      <div className="t">
                        #{item.vmid ?? "—"} {item.nama || "guest"}{" "}
                        <span className="mono" style={{ color: "var(--blue)", fontSize: 11 }}>
                          {item.aksi || "—"}
                        </span>
                        <span
                          className={`pill ${item.approved ? "mint" : "amber"}`}
                          style={{ height: 17, fontSize: 9.5, marginLeft: 6 }}
                        >
                          {item.approved ? `disetujui${item.oleh ? ` · ${item.oleh}` : ""}` : "menunggu"}
                        </span>
                      </div>
                      <div className="m">
                        {[item.jenis, item.jenis_guest, item.status, `sumber=${item.sumber}`]
                          .filter(Boolean)
                          .join(" · ")}
                        {!item.approved && item.seconds_left != null
                          ? ` · sisa ${fmtAge(item.seconds_left)}`
                          : ""}
                        {item.alasan ? ` · ${item.alasan}` : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="copy-command" style={{ marginTop: 12 }}>
              <div className="code-block">{approvalCommands}</div>
              <button
                type="button"
                className="copy-btn"
                aria-label="Copy approval commands"
                onClick={() => {
                  void navigator.clipboard
                    .writeText(approvalCommands)
                    .then(() => toast("Approval commands copied"))
                    .catch(() => toast("Clipboard tidak tersedia"));
                }}
              >
                <Icon name="i-copy" />
              </button>
            </div>
            <div className="ro-note" style={{ marginTop: 12 }}>
              <Icon name="i-lock" className="icon sm" />
              <span>
                Ops hanya membaca antrean. Tidak ada endpoint approve/reject — keputusan tetap di CLI{" "}
                <span className="mono">healer.py</span> pada VM105.
              </span>
            </div>
          </Panel>

          {goals ? (
            <Panel
              title="AI goal activity"
              sub="24 jam terakhir · summary healer"
              right={
                <Pill tone={goalCount ? "violet" : "neutral"}>
                  {goalCount != null ? `${goalCount} goal` : "—"}
                </Pill>
              }
              body
            >
              <div className="kv" style={{ borderTop: 0, paddingTop: 0 }}>
                <div>
                  <div className="k">goal_24h</div>
                  <div className="v" style={{ fontSize: 18 }}>{goalCount ?? "—"}</div>
                  <div className="hint">tidak dihitung sebagai insiden</div>
                </div>
                <div>
                  <div className="k">insiden_24h</div>
                  <div className="v" style={{ fontSize: 18 }}>{data?.summary.insiden_24h ?? "—"}</div>
                  <div className="hint">decision sumber non-goal</div>
                </div>
              </div>
              <div className="ro-note" style={{ marginTop: 12 }}>
                <Icon name={goalsExecute ? "i-key" : "i-lock"} className="icon sm" />
                <span>
                  {goalsExecute
                    ? "Eksekusi goal aktif; tetap butuh approval manusia dan klik execute terpisah."
                    : "GOALS_EXECUTE_ENABLED=false — goal berhenti di approved dan tidak ada aksi yang dikirim ke healer."}
                </span>
              </div>
            </Panel>
          ) : null}

          <Panel
            title="Auto-heal scope"
            sub="nilai runtime saat ini · dari /api/knobs"
            right={
              <Pill tone={dry ? "amber" : "mint"} dot={dry ? "amber" : "mint"}>
                {dry ? "DRY_RUN" : "AKSI AKTIF"}
              </Pill>
            }
            body
          >
            {loading && !data ? (
              <div className="empty">
                <span className="spinner" aria-hidden="true" /> memuat knob…
              </div>
            ) : (
              <>
                <div className="knob">
                  <div className="knob-label">
                    AUTO_IDS <span className="hint" style={{ fontWeight: 400 }}>guest yang boleh di-start/reset</span>
                  </div>
                  <div className="chipset">
                    {autoIds.length ? (
                      autoIds.map((vmid) => (
                        <span className="chip on" key={vmid}>
                          {vmid}
                        </span>
                      ))
                    ) : (
                      <span className="tiny dim">(kosong)</span>
                    )}
                  </div>
                </div>

                <div className="knob">
                  <div className="knob-label">
                    PROTECT <span className="hint" style={{ fontWeight: 400 }}>tidak pernah disentuh</span>
                  </div>
                  <div className="chipset">
                    {protect.length ? (
                      protect.map((vmid) => (
                        <span
                          className="chip on"
                          key={vmid}
                          style={{ color: "var(--amber)", borderColor: "rgba(255,197,98,.3)", background: "rgba(255,197,98,.08)" }}
                        >
                          {vmid}
                        </span>
                      ))
                    ) : (
                      <span className="tiny dim">(kosong)</span>
                    )}
                  </div>
                </div>

                <div className="form-row form-row-3">
                  <div className="knob">
                    <div className="knob-label">MAX_AKSI</div>
                    <div className="ro-value">{knobs.MAX_AKSI ?? "—"}</div>
                    <div className="hint">aksi per siklus</div>
                  </div>
                  <div className="knob">
                    <div className="knob-label">COOLDOWN</div>
                    <div className="ro-value">{knobs.COOLDOWN != null ? `${knobs.COOLDOWN} s` : "—"}</div>
                    <div className="hint">detik per guest</div>
                  </div>
                  <div className="knob">
                    <div className="knob-label">INTERVAL</div>
                    <div className="ro-value">{knobs.INTERVAL != null ? `${knobs.INTERVAL} s` : "—"}</div>
                    <div className="hint">detik per siklus</div>
                  </div>
                </div>

                <div className="form-row">
                  <div className="knob">
                    <div className="knob-label">
                      MINOR_ACTIONS{" "}
                      <span className="hint" style={{ fontWeight: 400 }}>boleh tanpa izin manusia</span>
                    </div>
                    <div className="chipset">
                      {minorActions.length ? (
                        minorActions.map((action) => (
                          <span className="chip on" key={action}>
                            {action}
                          </span>
                        ))
                      ) : (
                        <span className="tiny dim">(kosong)</span>
                      )}
                    </div>
                  </div>
                  <div className="knob">
                    <div className="knob-label">IZIN_TTL</div>
                    <div className="ro-value">{knobs.IZIN_TTL != null ? `${knobs.IZIN_TTL} s` : "—"}</div>
                    <div className="hint">masa berlaku izin minor</div>
                  </div>
                </div>

                <div className="form-row">
                  <div className="knob">
                    <div className="knob-label">K8S_NS</div>
                    <div className="ro-value">{k8sNs.length ? k8sNs.join(", ") : "(idle)"}</div>
                  </div>
                  <div className="knob">
                    <div className="knob-label">LLM decider</div>
                    <div className="ro-value">{knobs.LLM_AKTIF ? knobs.LLM_MODEL || "aktif" : "tidak dipakai"}</div>
                  </div>
                </div>

                <div className="knob">
                  <div className="knob-label">DRY_RUN</div>
                  <div className="ro-value">{dry ? "aktif (1)" : "nonaktif (0)"}</div>
                </div>

                <div className="knob">
                  <div className="knob-label">
                    NODES <span className="hint" style={{ fontWeight: 400 }}>IP host Proxmox</span>
                  </div>
                  <div className="kv" style={{ borderTop: "1px solid var(--line)", paddingTop: 12 }}>
                    {nodes.length ? (
                      nodes.map(([node, ip]) => (
                        <div key={node}>
                          <div className="k">{node}</div>
                          <div className="v" style={{ fontSize: 11 }}>
                            {ip}
                          </div>
                        </div>
                      ))
                    ) : (
                      <span className="tiny dim">(kosong)</span>
                    )}
                  </div>
                </div>
              </>
            )}
          </Panel>

          <Panel
            title="Apply changes (SSH)"
            sub="satu-satunya jalur ubah konfigurasi"
            right={<Pill>{ssh}</Pill>}
          >
            <div className="panel-body" id="apply" style={{ paddingTop: 0 }}>
              <div className="copy-command">
                <div className="code-block">{applyCommands}</div>
                <button
                  type="button"
                  className="copy-btn"
                  aria-label="Copy commands"
                  onClick={() => {
                    void navigator.clipboard
                      .writeText(applyCommands)
                      .then(() => toast("Commands copied"))
                      .catch(() => toast("Clipboard tidak tersedia"));
                  }}
                >
                  <Icon name="i-copy" />
                </button>
              </div>
              <div className="ro-note" style={{ marginTop: 12 }}>
                <Icon name="i-alert-triangle" className="icon sm" />
                <span>
                  Kalau env di-deploy dari laptop tanpa <span className="mono">LLM_KEY</span>, healer diam-diam
                  jatuh ke mode aturan. Setelah restart, cek baris startup <span className="mono">llm=ya</span>.
                </span>
              </div>
            </div>
          </Panel>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
          <Panel title="Decision pipeline" sub="yang terjadi tiap siklus">
            <div className="pipeline">
              {[
                ["Detect", "Baseline per vmid dari satu qm list; insiden = running → stopped."],
                ["Deterministic gate", "Cooldown, MAX_AKSI, guest-agent pernah jawab, revisi sebelumnya ada. Jawaban pasti → aturan yang bertindak."],
                ["Closed action set", "start · reset · noop · escalate · rollout undo. LLM tidak bisa memilih di luar daftar."],
                ["Verify", "±90 detik setelah aksi. Gagal → eskalasi, tanpa percobaan buta kedua."],
                ["Audit", "Satu baris decisions.jsonl per keputusan, plus metrik healer."]
              ].map(([title, description], index) => (
                <div className={`pipe-step${index === 1 ? " active" : ""}`} key={title}>
                  <span className="pipe-num">{String(index + 1).padStart(2, "0")}</span>
                  <div>
                    <div className="pipe-title">{title}</div>
                    <div className="pipe-desc">{description}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="Runtime"
            sub="state saat ini"
            right={
              <Pill
                tone={metrics?.healer_up === 1 ? "mint" : metrics?.healer_up === 0 ? "coral" : "neutral"}
                dot={metrics?.healer_up === 1 ? "mint" : metrics?.healer_up === 0 ? "coral" : "neutral"}
              >
                {metrics?.healer_up === 1 ? "up" : metrics?.healer_up === 0 ? "down" : "—"}
              </Pill>
            }
            body
          >
            <div className="kv" style={{ borderTop: 0, paddingTop: 0 }}>
              <div>
                <div className="k">Healer up</div>
                <div className="v">{metrics?.healer_up ?? "—"}</div>
              </div>
              <div>
                <div className="k">Mode</div>
                <div className="v">{dry ? "DRY_RUN" : "aktif"}</div>
              </div>
              <div>
                <div className="k">Menunggu persetujuan</div>
                <div className="v">{metrics?.pending ?? awaiting.length}</div>
              </div>
              <div>
                <div className="k">Eskalasi total</div>
                <div className="v">{metrics?.escalation_total ?? "—"}</div>
              </div>
              <div>
                <div className="k">Classifier</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {classifier?.configured
                    ? classifier.ok
                      ? `ok · ${classifier.model || "model"}`
                      : classifier.error || "gagal"
                    : "tidak dikonfigurasi"}
                </div>
              </div>
              <div>
                <div className="k">Engine healer · K3s</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {engine?.configured
                    ? engine.ok
                      ? `ok · ${engine.decisions.length} decisions`
                      : engine.error || "gagal"
                    : "tidak dikonfigurasi"}
                </div>
              </div>
              <div>
                <div className="k">K8S module</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {k8sNs.length ? k8sNs.join(", ") : "idle"}
                </div>
              </div>
              <div>
                <div className="k">Last decision</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {lastDecision ? `${timeOf(lastDecision.ts)} · ${lastDecision.aksi}` : "belum ada"}
                </div>
              </div>
            </div>
          </Panel>

          <Panel
            title="Metrik healer"
            sub="counter /metrics · per label"
            right={
              <>
                {links.grafana_healer_dashboard ? (
                  <a
                    className="panel-link"
                    href={links.grafana_healer_dashboard}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Grafana <Icon name="i-arrow-up-right" className="icon sm" />
                  </a>
                ) : null}
                <Pill>{actionTotals.length + approvalTotals.length} series</Pill>
              </>
            }
            body
          >
            <div className="sect-label">Aksi</div>
            <MetricRows items={actionTotals} />
            <div className="sect-label" style={{ marginTop: 14 }}>
              Insiden
            </div>
            <MetricRows items={incidentTotals} />
            <div className="sect-label" style={{ marginTop: 14 }}>
              Persetujuan
            </div>
            <MetricRows items={approvalTotals} />
            <div className="form-row" style={{ marginTop: 14 }}>
              <div className="knob">
                <div className="knob-label">Eskalasi total</div>
                <div className="ro-value">{metrics?.escalation_total ?? "—"}</div>
              </div>
              <div className="knob">
                <div className="knob-label">Node gagal</div>
                {nodeFailures.length ? (
                  <MetricRows items={nodeFailures} />
                ) : (
                  <div className="tiny dim">Belum ada series.</div>
                )}
              </div>
            </div>
            {k8sActionTotals.length || k8sEscalationTotals.length ? (
              <>
                <div className="sect-label" style={{ marginTop: 14 }}>
                  K3s
                </div>
                <MetricRows items={[...k8sActionTotals, ...k8sEscalationTotals]} />
              </>
            ) : null}
          </Panel>

          {engine?.configured ? (
            <Panel
              title="Engine healer · K3s"
              sub="keputusan terbaru dari /decisions"
              right={
                <Pill tone={engine.ok ? "mint" : "coral"} dot={engine.ok ? "mint" : "coral"}>
                  {engine.ok ? `${engine.decisions.length} decisions` : "gagal"}
                </Pill>
              }
              body
            >
              {engine.decisions.length === 0 ? (
                <div className="tiny dim">Belum ada decision dari engine healer.</div>
              ) : (
                <div className="event-list">
                  {engine.decisions.slice(0, 6).map((decision, index) => (
                    <div className="event" key={`${decision.ts}-${index}`}>
                      <div className="event-rail">
                        <span
                          className={`event-dot ${
                            decision.hasil === "pulih"
                              ? "mint"
                              : decision.hasil === "gagal"
                                ? "coral"
                                : "amber"
                          }`}
                        />
                      </div>
                      <div className="event-body">
                        <div className="t">
                          <span className="mono">{decision.target || "—"}</span>{" "}
                          <span className="mono" style={{ color: "var(--blue)", fontSize: 11 }}>
                            {decision.aksi || "—"}
                          </span>
                          <span
                            className={`pill ${decision.kelas === "manusia" ? "amber" : "neutral"}`}
                            style={{ height: 17, fontSize: 9.5, marginLeft: 6 }}
                          >
                            {decision.kelas || decision.jenis}
                          </span>
                        </div>
                        <div className="m">
                          {timeOf(decision.ts)} · {decision.jenis || "—"} · confidence{" "}
                          {decision.confidence != null ? decision.confidence.toFixed(2) : "—"}
                          {decision.hasil ? ` · hasil=${decision.hasil}` : ""}
                          {decision.dry_run ? " · DRY_RUN" : ""}
                          {decision.error ? ` · error=${decision.error}` : ""}
                          {decision.keterangan ? ` · ${decision.keterangan}` : ""}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          ) : null}
        </div>
      </div>
    </>
  );
}
