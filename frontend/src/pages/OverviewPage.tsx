import { Link } from "react-router-dom";
import { ActivityChart } from "../components/charts";
import { EndpointList } from "../components/EndpointList";
import { Icon } from "../components/Icon";
import {
  Empty,
  ErrorState,
  KpiCard,
  PageHead,
  Panel,
  Pill,
  LoadingPanel,
  Meter
} from "../components/ui";
import { hourlyBuckets, jobIcon, resultTone, timeOf } from "../data/format";
import type { Overview } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../state/auth";
import { useRefresh } from "../state/refresh";

export function OverviewPage() {
  const { data, error, loading } = useApi<Overview>("/api/overview", 15_000);
  const { info } = useAuth();
  const { refresh } = useRefresh();
  const plane = info?.plane;
  const eyebrow = plane
    ? `Live plane · ${[plane.site, plane.host].filter(Boolean).join(" · ")}`
    : "Live plane";

  const head = (
    <PageHead
      eyebrow={eyebrow}
      title="Plane overview"
      sub="Real state dari healer API, Prometheus dan Proxmox — termasuk keputusan yang sengaja tidak diambil."
      actions={
        <>
          {data ? (
            <Pill tone={data.summary.dry ? "amber" : "mint"} dot={data.summary.dry ? "amber" : "mint"} style={{ height: 30 }}>
              {data.summary.dry ? "DRY_RUN" : "AKSI AKTIF"}
            </Pill>
          ) : null}
          <button type="button" className="btn" onClick={refresh}>
            <Icon name="i-refresh" /> Refresh
          </button>
          <Link className="btn btn-primary" to="/incidents">
            <Icon name="i-activity" /> Open incidents
          </Link>
        </>
      }
    />
  );

  if (loading && !data) {
    return (
      <>
        {head}
        <LoadingPanel label="memuat overview dari healer API…" />
      </>
    );
  }
  if (!data) {
    return (
      <>
        {head}
        <ErrorState message={error ?? "unknown error"} onRetry={refresh} />
      </>
    );
  }

  const summary = data.summary;
  const targets = summary.targets;
  const alerts = data.alerts;
  const nodes = Object.keys(data.guests.nodes);
  const buckets = hourlyBuckets(data.decisions, 24);
  const decisionCount = buckets.reduce((sum, bucket) => sum + bucket.total, 0);
  const escalationCount = buckets.reduce((sum, bucket) => sum + bucket.escalated, 0);
  const critical = alerts.counts.critical ?? 0;
  const warning = alerts.counts.warning ?? 0;
  const jobsShown = data.jobs.slice(0, 6);

  return (
    <>
      {head}
      {error ? <ErrorState message={error} onRetry={refresh} title="Data mungkin sudah basi" /> : null}

      {summary.menunggu_persetujuan > 0 ? (
        <div className="banner">
          <div className="banner-ico">
            <Icon name="i-user" className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">
              {summary.menunggu_persetujuan} aksi menunggu persetujuan manusia
            </div>
            <div className="banner-sub">
              Antrean dari <span className="mono">/api/pending</span>. Approval hanya lewat CLI di VM105 — tidak
              ada endpoint approve/reject di Ops.
            </div>
          </div>
          <div className="banner-actions">
            <Link className="btn btn-sm" to="/healer">
              Lihat antrean
            </Link>
          </div>
        </div>
      ) : null}

      {!alerts.ok ? (
        <div className="banner">
          <div className="banner-ico">
            <Icon name="i-alert-triangle" className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">Prometheus alerts tidak terjangkau</div>
            <div className="banner-sub">Panel API endpoints menunjukkan sumber mana yang gagal.</div>
          </div>
        </div>
      ) : critical > 0 ? (
        <div className="banner crit">
          <div className="banner-ico">
            <Icon name="i-alert-triangle" className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">
              {critical} critical alert{critical === 1 ? "" : "s"} · {alerts.instances} firing total
            </div>
            <div className="banner-sub">
              <span className="mono">
                {alerts.groups
                  .filter((group) => group.severity === "critical")
                  .slice(0, 3)
                  .map((group) => `${group.name} (${group.instances})`)
                  .join(" · ")}
              </span>
              <span className="sep">·</span> {warning} warning alerts
            </div>
          </div>
          <div className="banner-actions">
            <Link className="btn btn-sm" to="/incidents">
              Triage incidents
            </Link>
            <a className="btn btn-sm" href={`${data.links.prometheus}/alerts`} target="_blank" rel="noreferrer">
              Prometheus <Icon name="i-arrow-up-right" className="icon sm" />
            </a>
          </div>
        </div>
      ) : warning > 0 ? (
        <div className="banner">
          <div className="banner-ico">
            <Icon name="i-bell" className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">
              {alerts.instances} alerts firing · {alerts.groups.length} groups
            </div>
            <div className="banner-sub mono">
              {alerts.groups
                .slice(0, 4)
                .map((group) => `${group.name} (${group.instances})`)
                .join(" · ")}
            </div>
          </div>
          <div className="banner-actions">
            <Link className="btn btn-sm" to="/incidents">
              Triage incidents
            </Link>
          </div>
        </div>
      ) : (
        <div className="banner ok">
          <div className="banner-ico">
            <Icon name="i-check-circle" className="icon lg" />
          </div>
          <div className="banner-body">
            <div className="banner-title">Plane nominal — tidak ada alert firing</div>
          </div>
        </div>
      )}

      <div className="kpis">
        <KpiCard
          icon="i-box"
          label="Guests running"
          pill={
            <Pill tone={summary.stopped ? "amber" : "mint"} style={{ marginLeft: "auto" }}>
              {summary.stopped} stopped
            </Pill>
          }
          value={summary.running}
          of={summary.total}
          note={`${nodes.length} node Proxmox · state.json`}
          meter={
            <Meter
              segments={[
                ["", summary.running],
                ["muted", summary.stopped]
              ]}
            />
          }
        />
        <KpiCard
          icon="i-target"
          label="Targets up"
          pill={
            <Pill tone={targets.down ? "amber" : "mint"} style={{ marginLeft: "auto" }}>
              {targets.down ? `${targets.down} down` : "all up"}
            </Pill>
          }
          value={targets.up}
          of={targets.total}
          note={`${data.jobs.length} scrape jobs · Prometheus`}
          meter={
            <Meter
              segments={[
                ["", targets.up],
                ["coral", targets.down]
              ]}
            />
          }
        />
        <KpiCard
          icon="i-bell"
          label="Alerts firing"
          pill={
            <Pill tone={critical ? "coral" : "neutral"} style={{ marginLeft: "auto" }}>
              {critical} critical
            </Pill>
          }
          value={alerts.instances}
          note={`${alerts.groups.length} groups · ${warning} warning`}
          meter={
            <Meter
              segments={[
                ["coral", critical],
                ["amber", warning],
                ["blue", alerts.counts.info ?? 0],
                ["muted", alerts.counts.none ?? 0]
              ]}
            />
          }
        />
        <KpiCard
          icon="i-shield"
          label="Healer actions · 24h"
          pill={
            <Pill tone="mint" style={{ marginLeft: "auto" }}>
              {summary.pulih_24h} recovered
            </Pill>
          }
          value={summary.aksi_24h}
          note={`${summary.eskalasi_24h} escalated · ${summary.insiden_24h} incidents${
            summary.menunggu_persetujuan ? ` · ${summary.menunggu_persetujuan} awaiting approval` : ""
          }`}
          meter={
            <Meter
              segments={[
                ["", summary.pulih_24h],
                ["amber", summary.eskalasi_24h]
              ]}
            />
          }
        />
      </div>

      <div className="grid grid-2">
        <Panel
          title="Scrape jobs"
          sub="Prometheus"
          right={<Pill>{data.jobs.length} jobs</Pill>}
        >
          <div className="comp-list">
            {data.jobs.length === 0 ? (
              <Empty>Tidak ada data scrape job.</Empty>
            ) : (
              jobsShown.map((job) => {
                const [icon, tone] = jobIcon(job.job);
                const bad = job.down > 0;
                return (
                  <div className="comp" key={job.job}>
                    <span className={`comp-ico ${tone}`}>
                      <Icon name={icon} />
                    </span>
                    <div className="comp-main">
                      <div className="comp-name">{job.job}</div>
                      <div className="comp-meta">
                        scrape job · {job.up} target{bad ? ` · ${job.down} down` : ""}
                      </div>
                    </div>
                    <div className="comp-right">
                      <div className="comp-stat">
                        {job.up}
                        <small>up</small>
                      </div>
                      <span className={`dot ${bad ? "amber" : "mint"}`} />
                    </div>
                  </div>
                );
              })
            )}
          </div>
          {data.jobs.length > jobsShown.length ? (
            <>
              <div className="panel-sep" />
              <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "12px 18px" }}>
                <span className="tiny dim">+{data.jobs.length - jobsShown.length} more scrape jobs</span>
                <Link className="panel-link" to="/raw" style={{ marginLeft: "auto" }}>
                  Raw <Icon name="i-arrow-right" className="icon sm" />
                </Link>
              </div>
            </>
          ) : null}
        </Panel>

        <Panel
          title="Healer decisions"
          sub="terbaru di atas"
          right={
            <>
              <Pill>{data.decisions.length} recent</Pill>
              <Link className="panel-link" to="/raw">
                Raw <Icon name="i-arrow-right" className="icon sm" />
              </Link>
            </>
          }
        >
          <div className="decisions">
            {data.decisions.length === 0 ? (
              <Empty>Belum ada keputusan di decisions.jsonl.</Empty>
            ) : (
              data.decisions.slice(0, 6).map((decision, index) => (
                <div className="decision" key={`${decision.ts}-${index}`}>
                  <div className="decision-time">{timeOf(decision.ts)}</div>
                  <div className="decision-main">
                    <div className="decision-title">
                      <span className="mono">{decision.target}</span>{" "}
                      <span className="action">{decision.aksi}</span>
                    </div>
                    <div className="decision-meta">
                      <Pill tone={decision.sumber === "llm" ? "violet" : "neutral"}>{decision.sumber}</Pill>
                      {decision.jenis ? <Pill>{decision.jenis}</Pill> : null}
                      {decision.izin ? (
                        <Pill tone={decision.izin === "manusia" ? "amber" : "neutral"}>{decision.izin}</Pill>
                      ) : null}
                      <span className="sep">·</span>
                      {decision.alasan.slice(0, 84) || "tanpa alasan"}
                    </div>
                  </div>
                  <Pill tone={resultTone(decision.hasil)}>{decision.hasil}</Pill>
                </div>
              ))
            )}
          </div>
        </Panel>
      </div>

      <div className="grid grid-2 mt-14">
        <Panel
          title="Healer activity"
          sub="decisions per hour · last 24h"
          right={
            <>
              <Pill tone="blue">{decisionCount} decisions</Pill>
              <Pill tone="amber">{escalationCount} escalations</Pill>
            </>
          }
        >
          <div className="chart-wrap">
            <ActivityChart buckets={buckets} />
          </div>
          <div className="chart-legend">
            <span className="key">
              <span className="line-key" style={{ background: "var(--blue)" }} />
              decisions
            </span>
            <span className="key">
              <span className="line-key" style={{ background: "var(--amber)" }} />
              escalations
            </span>
          </div>
        </Panel>

        <Panel
          title="API endpoints"
          sub="read-only"
          right={
            <a className="panel-link" href={data.links.grafana} target="_blank" rel="noreferrer">
              Grafana <Icon name="i-arrow-up-right" className="icon sm" />
            </a>
          }
        >
          <div className="checks">
            <EndpointList endpoints={data.endpoints} />
          </div>
        </Panel>
      </div>
    </>
  );
}
