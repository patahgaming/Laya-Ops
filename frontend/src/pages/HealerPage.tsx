import { Icon } from "../components/Icon";
import { ErrorState, PageHead, Panel, Pill } from "../components/ui";
import { timeOf } from "../data/format";
import type { KnobsResponse } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useRefresh } from "../state/refresh";
import { useToast } from "../state/toast";

const APPLY_COMMANDS = [
  "# 1. edit env runtime (env var, bukan file di repo)",
  "ssh root@10.10.0.107 'sudoedit /etc/proxmox-healer.env'",
  "",
  "# 2. restart lalu pastikan unit hidup",
  "ssh root@10.10.0.107 'systemctl restart proxmox-healer && systemctl is-active proxmox-healer'",
  "",
  "# 3. verifikasi knob yang benar-benar aktif",
  "curl -s http://10.10.0.107:9181/api/knobs | jq .",
  "",
  "# 4. lihat baris startup (llm=ya|tidak, auto=[...])",
  "ssh root@10.10.0.107 'journalctl -u proxmox-healer -n 5 --no-pager'"
].join("\n");

export function HealerPage() {
  const { data, error, loading } = useApi<KnobsResponse>("/api/knobs", 30_000);
  const { refresh } = useRefresh();
  const toast = useToast();
  const knobs = data?.knobs ?? {};
  const dry = Boolean(knobs.DRY_RUN);
  const autoIds = knobs.AUTO_IDS ?? [];
  const protect = knobs.PROTECT ?? [];
  const k8sNs = knobs.K8S_NS ?? [];
  const nodes = Object.entries(knobs.NODES ?? {});
  const metrics = data?.metrics;
  const lastDecision = data?.last_decision;

  return (
    <>
      <PageHead
        eyebrow="Control · knob runtime · read-only"
        title="Healer"
        sub="Konfigurasi aktif healer dari /api/knobs. Gate deterministik memutuskan; LLM hanya memilih di dalam daftar aksi tertutup. Tidak ada endpoint aksi dari UI."
        actions={
          <>
            <Pill tone={dry ? "amber" : "mint"} dot={dry ? "amber" : "mint"} style={{ height: 30 }}>
              {dry ? "DRY_RUN" : "aksi aktif"}
            </Pill>
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

      <div className="ro-note" style={{ marginBottom: 14 }}>
        <Icon name="i-lock" className="icon sm" />
        <span>
          <b>Read-only console.</b> Knob tinggal di <span className="mono">/etc/proxmox-healer.env</span> dan
          dibaca runtime; untuk mengubahnya perlu edit env + <span className="mono">systemctl restart proxmox-healer</span>{" "}
          lewat SSH. UI ini tidak punya jalur tulis, ack, atau trigger aksi.
        </span>
      </div>

      <div className="settings">
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
                  <div className="hint">Satu aksi per siklus (MAX_AKSI), lalu cooldown per guest.</div>
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
                  <div className="hint">105 = VM rumah healer sendiri.</div>
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
                    <div className="knob-label">K8S_NS</div>
                    <div className="ro-value">{k8sNs.length ? k8sNs.join(", ") : "(idle)"}</div>
                    <div className="hint">kosong = modul k8s idle</div>
                  </div>
                  <div className="knob">
                    <div className="knob-label">LLM decider</div>
                    <div className="ro-value">{knobs.LLM_AKTIF ? knobs.LLM_MODEL || "aktif" : "tidak dipakai"}</div>
                    <div className="hint">output divalidasi ke daftar aksi</div>
                  </div>
                </div>

                <div className="knob">
                  <div className="knob-label">DRY_RUN</div>
                  <div className="ro-value">{dry ? "aktif (1)" : "nonaktif (0)"}</div>
                  <div className="hint">dry = catat + eskalasi saja, tidak ada aksi.</div>
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
            right={<Pill>root@10.10.0.107</Pill>}
          >
            <div className="panel-body" id="apply" style={{ paddingTop: 0 }}>
              <div className="copy-command">
                <div className="code-block">{APPLY_COMMANDS}</div>
                <button
                  type="button"
                  className="copy-btn"
                  aria-label="Copy commands"
                  onClick={() => {
                    void navigator.clipboard
                      .writeText(APPLY_COMMANDS)
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
                ["Audit", "Satu baris decisions.jsonl per keputusan, plus metrik :9181."]
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
              <Pill tone={metrics?.healer_up === 1 ? "mint" : metrics?.healer_up === 0 ? "coral" : "neutral"} dot={metrics?.healer_up === 1 ? "mint" : "coral"}>
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
                <div className="k">Last decision</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {lastDecision ? `${timeOf(lastDecision.ts)} · ${lastDecision.aksi}` : "belum ada"}
                </div>
              </div>
              <div>
                <div className="k">K8S module</div>
                <div className="v" style={{ fontSize: 11 }}>
                  {k8sNs.length ? k8sNs.join(", ") : "idle"}
                </div>
              </div>
            </div>
            <div className="tiny dim" style={{ marginTop: 14 }}>
              Sumber: <span className="mono">/api/knobs</span>, <span className="mono">/api/decisions</span>,{" "}
              <span className="mono">/metrics</span> · <span className="mono">pve_healer_up</span>.
            </div>
          </Panel>

          <Panel title="Yang tidak bisa dilakukan UI" sub="by design">
            <div className="checks">
              {[
                ["Tidak ada endpoint aksi", "start/reset/undo hanya dari loop healer", "i-x", "tone-coral"],
                ["Tidak ada autentikasi UI", "bind ke LAN / tunnel; jangan expose :9181", "i-x", "tone-coral"],
                ["Grafana tidak di-query", "pakai link Grafana langsung", "i-info", "tone-amber"]
              ].map(([title, description, icon, tone]) => (
                <div className="check" key={title}>
                  <span className={`check-ico ${tone}`}>
                    <Icon name={icon} />
                  </span>
                  <div className="check-main">
                    <div className="check-name">{title}</div>
                    <div className="check-val">{description}</div>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
