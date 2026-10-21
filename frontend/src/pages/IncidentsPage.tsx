import { useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { Empty, ErrorState, PageHead, Panel, Pill } from "../components/ui";
import { fmtAge, severityClass, severityTone, timeOf } from "../data/format";
import type { AlertGroup, AlertsResponse, DecisionsResponse } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useRefresh } from "../state/refresh";
import { useToast } from "../state/toast";

const SEV_LABEL: Record<string, string> = {
  critical: "CRITICAL",
  warning: "WARNING",
  info: "INFO",
  none: "WATCHDOG"
};

export function IncidentsPage() {
  const { data, error, loading } = useApi<AlertsResponse>("/api/alerts", 15_000);
  const { data: decisionsData } = useApi<DecisionsResponse>("/api/decisions?limit=20", 30_000);
  const { refresh } = useRefresh();
  const [selected, setSelected] = useState<string | null>(null);

  const groups = data?.groups ?? [];
  const current =
    groups.find((group) => group.name === selected) ?? groups[0] ?? null;
  const decisions = decisionsData?.decisions ?? [];

  return (
    <>
      <PageHead
        eyebrow="Incidents · Prometheus ALERTS · dibaca lewat proxy backend"
        title="Incidents"
        sub="Alert group Prometheus yang sedang firing, alert push healer dari Alertmanager, dan keputusan healer terakhir. Alert group = alertname; instance = target yang kena."
        actions={
          <>
            <Pill
              tone={data && data.counts.critical ? "coral" : data && data.instances ? "amber" : "mint"}
              dot={data && data.counts.critical ? "coral" : data && data.instances ? "amber" : "mint"}
              style={{ height: 30 }}
            >
              {data ? `${data.instances} firing · ${data.groups.length} groups` : "loading…"}
            </Pill>
            <button type="button" className="btn" onClick={refresh}>
              <Icon name="i-refresh" /> Refresh
            </button>
            <Link className="btn btn-primary" to="/raw">
              <Icon name="i-terminal" /> Raw data
            </Link>
          </>
        }
      />

      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      <div className="inc-layout">
        <Panel
          title="Alert groups"
          sub="currently firing"
          right={<Pill>{data ? `${data.instances} instances` : "—"}</Pill>}
        >
          <div className="inc-list">
            {loading && !data ? (
              <div className="empty">
                <span className="spinner" aria-hidden="true" /> memuat alert…
              </div>
            ) : groups.length === 0 ? (
              <Empty>{data?.ok ? "Tidak ada alert firing." : "Prometheus alerts tidak terjangkau."}</Empty>
            ) : (
              groups.map((group) => (
                <button
                  key={group.name}
                  type="button"
                  className={`inc-item${current?.name === group.name ? " active" : ""}`}
                  onClick={() => setSelected(group.name)}
                >
                  <div className="inc-item-top">
                    <span className={`sev ${severityClass(group.severity)}`}>
                      {SEV_LABEL[group.severity] ?? group.severity}
                    </span>
                    <span className="age">{group.instances} firing</span>
                  </div>
                  <div className="inc-title">{group.name}</div>
                  <div className="inc-tags">
                    {group.namespaces.length ? (
                      <>
                        {group.namespaces.slice(0, 3).map((namespace) => (
                          <Pill key={namespace}>{namespace}</Pill>
                        ))}
                        {group.namespaces.length > 3 ? <Pill>+{group.namespaces.length - 3}</Pill> : null}
                      </>
                    ) : (
                      <Pill>no namespace</Pill>
                    )}
                    {group.oldest_seconds != null ? (
                      <Pill>oldest {fmtAge(group.oldest_seconds)}</Pill>
                    ) : null}
                  </div>
                </button>
              ))
            )}
          </div>
        </Panel>

        <section className="panel inc-detail">
          {current ? (
            <AlertDetail group={current} decisions={decisions} links={data?.links ?? {}} />
          ) : (
            <Empty>{loading ? "memuat alert…" : "Tidak ada alert untuk ditampilkan."}</Empty>
          )}
        </section>
      </div>

      <Panel
        className="mt-14"
        title="Healer push alerts"
        sub="Alertmanager /api/v2/alerts · PveHealer* / Healer* — tidak muncul di Prometheus ALERTS"
        right={
          data ? (
            <Pill
              tone={data.pushed_ok ? (data.pushed.length ? "amber" : "mint") : "coral"}
              dot={data.pushed_ok ? (data.pushed.length ? "amber" : "mint") : "coral"}
            >
              {data.pushed_ok ? `${data.pushed.length} active` : "tidak terjangkau"}
            </Pill>
          ) : null
        }
      >
        <div className="comp-list">
          {!data?.pushed_ok ? (
            <Empty>Alertmanager /api/v2/alerts tidak terjangkau.</Empty>
          ) : data.pushed.length === 0 ? (
            <Empty>Tidak ada alert push dari healer.</Empty>
          ) : (
            data.pushed.map((alert) => (
              <div className="comp" key={alert.fingerprint || `${alert.alertname}-${alert.starts_at}`}>
                <span className={`comp-ico ${alert.severity === "critical" ? "tone-coral" : "tone-amber"}`}>
                  <Icon name="i-bell" />
                </span>
                <div className="comp-main">
                  <div className="comp-name">
                    {alert.alertname}
                    <span
                      className={`pill ${alert.status === "active" ? "amber" : "mint"}`}
                      style={{ height: 17, fontSize: 9.5, marginLeft: 6 }}
                    >
                      {alert.status}
                    </span>
                  </div>
                  <div className="comp-meta">
                    {alert.summary || "tanpa summary"}
                    {alert.labels.vmid ? ` · vmid=${alert.labels.vmid}` : ""}
                    {alert.labels.node ? ` · node=${alert.labels.node}` : ""}
                    {alert.labels.namespace ? ` · ns=${alert.labels.namespace}` : ""}
                  </div>
                  {alert.description ? <div className="comp-meta mono">{alert.description}</div> : null}
                </div>
                <div className="comp-right">
                  <div className="comp-stat">
                    {timeOf(alert.starts_at)}
                    <small>sejak</small>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      </Panel>
    </>
  );
}

function AlertDetail({
  group,
  decisions,
  links
}: {
  group: AlertGroup;
  decisions: DecisionsResponse["decisions"];
  links: Record<string, string>;
}) {
  const namespaces = group.namespaces;
  const matches = (target: string) => namespaces.some((namespace) => target.includes(namespace));
  const relevant = decisions.filter((decision) => matches(decision.target));
  const context = relevant.length ? relevant : decisions.slice(0, 5);
  const runbookText = group.runbook.lines.join("\n");
  const prometheus = links.prometheus?.replace(/\/$/, "");
  const alertmanager = links.alertmanager?.replace(/\/$/, "");

  return (
    <>
      <div className="detail-head">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className={`sev ${severityClass(group.severity)}`}>{SEV_LABEL[group.severity] ?? group.severity}</span>
          <span className="mono tiny dim">alert group</span>
          <span style={{ marginLeft: "auto" }} />
          <Pill tone={severityTone(group.severity)} dot={severityTone(group.severity)}>
            {group.instances} firing
          </Pill>
        </div>
        <div className="detail-title" style={{ marginTop: 10 }}>
          {group.name}
        </div>
        <div className="detail-meta">
          {[
            ["Instances", String(group.instances)],
            ["Namespaces", String(group.namespaces.length)],
            ["Oldest", group.oldest_seconds != null ? fmtAge(group.oldest_seconds) : "—"],
            ["Severity", SEV_LABEL[group.severity] ?? group.severity]
          ].map(([label, value]) => (
            <div key={label}>
              <div className="sect-label" style={{ margin: "0 0 3px" }}>
                {label}
              </div>
              <div className="mono" style={{ fontSize: 12 }}>
                {value}
              </div>
            </div>
          ))}
        </div>
        <p className="detail-summary">
          {group.name} firing pada {group.instances} target
          {group.namespaces.length ? ` di namespace ${group.namespaces.join(", ")}` : ""}.{" "}
          {group.oldest_seconds != null ? `Instance tertua sudah firing ${fmtAge(group.oldest_seconds)}. ` : ""}
          Annotation lengkap tidak diekspos oleh proxy backend; buka Prometheus untuk teks alert penuh.
        </p>
        <div className="ns-chips">
          {group.namespaces.map((namespace) => (
            <span className="ns-chip" key={namespace}>
              {namespace}
            </span>
          ))}
          {group.jobs.map((job) => (
            <span className="ns-chip" key={job}>
              job:{job}
            </span>
          ))}
        </div>
      </div>

      <div className="detail-cols">
        <div>
          <div className="sect-label">Healer context · decisions terakhir</div>
          <div className="event-list">
            {context.length === 0 ? (
              <div className="tiny dim">Belum ada decisions.</div>
            ) : (
              context.slice(0, 5).map((decision, index) => {
                const highlighted = matches(decision.target);
                return (
                  <div className="event" key={`${decision.ts}-${index}`}>
                    <div className="event-rail">
                      <span
                        className={`event-dot ${
                          decision.hasil === "pulih" ? "mint" : decision.hasil === "gagal" ? "coral" : "amber"
                        }`}
                      />
                    </div>
                    <div className="event-body">
                      <div className="t">
                        {decision.target}{" "}
                        <span className="mono" style={{ color: "var(--blue)", fontSize: 11 }}>
                          {decision.aksi}
                        </span>
                        {highlighted ? (
                          <span className="pill blue" style={{ height: 17, fontSize: 9.5, marginLeft: 4 }}>
                            namespace match
                          </span>
                        ) : null}
                      </div>
                      <div className="m">
                        {timeOf(decision.ts)} · sumber={decision.sumber} · hasil={decision.hasil} ·{" "}
                        {decision.alasan.slice(0, 100)}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
          <div className="ro-note" style={{ marginTop: 14 }}>
            <Icon name="i-info" className="icon sm" />
            <span>
              {relevant.length
                ? `${relevant.length} decision menyebut namespace alert ini.`
                : "Tidak ada decision yang menyebut namespace ini — menampilkan decisions terakhir secara global."}
            </span>
          </div>
        </div>
        <div>
          <div className="sect-label">Runbook (read-only)</div>
          <div className="copy-command">
            <div className="code-block">{runbookText}</div>
            <CopyIconButton text={runbookText} />
          </div>
          <div className="sect-label" style={{ margin: "18px 0 8px" }}>
            Links
          </div>
          {prometheus ? (
            <a
              className="btn btn-sm btn-block"
              style={{ justifyContent: "flex-start", marginBottom: 8 }}
              href={`${prometheus}/alerts`}
              target="_blank"
              rel="noreferrer"
            >
              Prometheus · /alerts{" "}
              <Icon name="i-arrow-up-right" className="icon sm" style={{ marginLeft: "auto" }} />
            </a>
          ) : null}
          {alertmanager ? (
            <a
              className="btn btn-sm btn-block"
              style={{ justifyContent: "flex-start" }}
              href={`${alertmanager}/#/alerts`}
              target="_blank"
              rel="noreferrer"
            >
              Alertmanager · alerts{" "}
              <Icon name="i-arrow-up-right" className="icon sm" style={{ marginLeft: "auto" }} />
            </a>
          ) : null}
        </div>
      </div>

      <div className="detail-foot">
        <span className="tiny dim">
          Tidak ada endpoint ack/silence — lakukan di Alertmanager atau lewat playbook.
        </span>
        <span className="note">read-only</span>
      </div>
    </>
  );
}

function CopyIconButton({ text }: { text: string }) {
  const toast = useToast();
  return (
    <button
      type="button"
      className="copy-btn"
      aria-label="Copy runbook"
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => toast("Runbook copied"))
          .catch(() => toast("Clipboard tidak tersedia"));
      }}
    >
      <Icon name="i-copy" />
    </button>
  );
}
