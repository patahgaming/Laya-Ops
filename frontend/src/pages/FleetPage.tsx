import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Icon } from "../components/Icon";
import { CopyButton, Empty, ErrorState, PageHead, Panel, Pill } from "../components/ui";
import { guestLabel, timeOf } from "../data/format";
import type { Guest, GuestsResponse } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useRefresh } from "../state/refresh";

const PAGE_SIZE = 12;
const NODE_TONE: Record<string, string> = { hq1: "mint", hq2: "blue", hq3: "violet" };
type StatusFilter = "all" | "running" | "stopped" | "agent-ok" | "agent-silent";

export function FleetPage() {
  const { data, error, loading } = useApi<GuestsResponse>("/api/guests", 20_000);
  const { refresh } = useRefresh();
  const [nodeFilter, setNodeFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [active, setActive] = useState<Guest | null>(null);

  const guests = data?.guests.guests ?? [];
  const nodes = Object.keys(data?.guests.nodes ?? {}).sort();

  const filtered = useMemo(() => {
    const search = query.trim().toLowerCase();
    return guests.filter((guest) => {
      if (nodeFilter !== "all" && guest.node !== nodeFilter) return false;
      if (statusFilter === "running" && guest.status !== "running") return false;
      if (statusFilter === "stopped" && guest.status === "running") return false;
      if (statusFilter === "agent-ok" && !guest.agent_ok) return false;
      if (statusFilter === "agent-silent" && guest.agent_ok) return false;
      if (search) {
        const haystack = `${guest.vmid} ${guest.name ?? ""} ${guest.node}`.toLowerCase();
        if (!haystack.includes(search)) return false;
      }
      return true;
    });
  }, [guests, nodeFilter, statusFilter, query]);

  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages);
  const start = (currentPage - 1) * PAGE_SIZE;
  const visible = filtered.slice(start, start + PAGE_SIZE);

  const resetPage = () => setPage(1);
  const closeDrawer = () => setActive(null);
  const inspectCommand = active
    ? `ssh root@10.10.0.107 'qm status ${active.vmid} || pct status ${active.vmid}'`
    : "";

  return (
    <>
      <PageHead
        eyebrow={data ? `Fleet · ${guests.length} guests · ${nodes.length} nodes` : "Fleet · loading…"}
        title="Fleet"
        sub="Guest Proxmox yang diawasi healer — state.json per siklus 60 s, plus aksi terakhir yang tercatat untuk tiap vmid."
        actions={
          <>
            <button type="button" className="btn" onClick={refresh}>
              <Icon name="i-refresh" /> Refresh
            </button>
            <Link className="btn btn-primary" to="/raw">
              <Icon name="i-terminal" /> Raw state
            </Link>
          </>
        }
      />

      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      <Panel
        title="Supervised guests"
        sub={data ? `${guests.length} guests · ${nodes.length} nodes · read-only` : "memuat state…"}
        right={<Pill>{guests.length} guests</Pill>}
      >
        <div className="toolbar">
          <div className="tabs" role="tablist">
            <button
              type="button"
              className={`tab${nodeFilter === "all" ? " active" : ""}`}
              onClick={() => {
                setNodeFilter("all");
                resetPage();
              }}
            >
              All <span className="count">{guests.length}</span>
            </button>
            {nodes.map((node) => (
              <button
                key={node}
                type="button"
                className={`tab${nodeFilter === node ? " active" : ""}`}
                onClick={() => {
                  setNodeFilter(node);
                  resetPage();
                }}
              >
                {node} <span className="count">{data?.guests.nodes[node] ?? 0}</span>
              </button>
            ))}
          </div>
          <div className="grow" />
          <div className="chips">
            {(
              [
                ["all", "All"],
                ["running", "Running"],
                ["stopped", "Stopped"],
                ["agent-ok", "Agent ok"],
                ["agent-silent", "Agent silent"]
              ] as Array<[StatusFilter, string]>
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`chip${statusFilter === value ? " active" : ""}`}
                onClick={() => {
                  setStatusFilter(value);
                  resetPage();
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="input-wrap" style={{ width: 200 }}>
            <Icon name="i-search" />
            <input
              className="input"
              placeholder="Filter vmid / node"
              style={{ height: 34, fontSize: 12.5 }}
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
                resetPage();
              }}
              aria-label="Filter guests"
            />
          </div>
        </div>

        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>ID</th>
                <th>Guest</th>
                <th>Node</th>
                <th>Agent</th>
                <th>Baseline</th>
                <th>Status</th>
                <th>Last action</th>
              </tr>
            </thead>
            <tbody>
              {loading && !data ? (
                <tr>
                  <td colSpan={7} className="empty">
                    <span className="spinner" aria-hidden="true" /> memuat state…
                  </td>
                </tr>
              ) : visible.length === 0 ? (
                <tr>
                  <td colSpan={7} className="empty">
                    Tidak ada guest yang cocok dengan filter.
                  </td>
                </tr>
              ) : (
                visible.map((guest) => (
                  <tr
                    key={guest.vmid}
                    tabIndex={0}
                    onClick={() => setActive(guest)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") setActive(guest);
                    }}
                  >
                    <td className="cell-id">#{guest.vmid}</td>
                    <td>
                      <div className="cell-agent">
                        <span className={`agent-avatar ${NODE_TONE[guest.node] ?? "mint"}`}>
                          <Icon name="i-box" />
                        </span>
                        <div>
                          <div className="agent-name">{guestLabel(guest)}</div>
                          <div className="agent-sub">vmid {guest.vmid}</div>
                        </div>
                      </div>
                    </td>
                    <td className="cell-id" style={{ color: "var(--muted)" }}>
                      {guest.node || "—"}
                    </td>
                    <td>
                      {guest.agent_ok ? (
                        <Pill tone="mint">qga ok</Pill>
                      ) : (
                        <Pill tone="amber">silent{guest.agent_gagal ? ` · ${guest.agent_gagal}` : ""}</Pill>
                      )}
                    </td>
                    <td className="cell-time">{guest.sejak || "—"}</td>
                    <td>
                      <span className={`status ${guest.status === "running" ? "healthy" : "down"}`}>
                        <span className={`dot ${guest.status === "running" ? "mint" : "coral"}`} />
                        {guest.status}
                      </span>
                    </td>
                    <td className="cell-task">
                      {guest.last_action ? (
                        <>
                          {guest.last_action.aksi}{" "}
                          <span className="muted">· {timeOf(guest.last_action.ts)}</span>
                        </>
                      ) : (
                        <span className="dim">—</span>
                      )}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="table-foot">
          <span>
            Showing {filtered.length ? start + 1 : 0}–{Math.min(start + PAGE_SIZE, filtered.length)} of{" "}
            {filtered.length} guests · {guests.length} total
          </span>
          <span style={{ color: "var(--faint)" }}>·</span>
          <span>read-only</span>
          <span className="right">
            <button
              type="button"
              className="page-btn"
              disabled={currentPage === 1}
              onClick={() => setPage(currentPage - 1)}
              aria-label="Previous page"
            >
              <Icon name="i-arrow-left" className="icon sm" />
            </button>
            {Array.from({ length: pages }, (_, index) => index + 1).map((number) => (
              <button
                key={number}
                type="button"
                className={`page-btn${number === currentPage ? " active" : ""}`}
                onClick={() => setPage(number)}
              >
                {number}
              </button>
            ))}
            <button
              type="button"
              className="page-btn"
              disabled={currentPage === pages}
              onClick={() => setPage(currentPage + 1)}
              aria-label="Next page"
            >
              <Icon name="i-arrow-right" className="icon sm" />
            </button>
          </span>
        </div>
      </Panel>

      <div className={`scrim${active ? " open" : ""}`} onClick={closeDrawer} />
      <aside className={`drawer${active ? " open" : ""}`} aria-label="Guest detail" aria-hidden={!active}>
        <div className="drawer-head">
          <div>
            <div className="title">Guest detail</div>
            <div className="sub">{active ? `#${active.vmid} · ${active.node}` : "#—"}</div>
          </div>
          <button type="button" className="btn-icon drawer-close" onClick={closeDrawer} aria-label="Close">
            <Icon name="i-x" />
          </button>
        </div>
        <div className="drawer-body">
          {active ? (
            <>
              <div className="drawer-hero">
                <span className={`agent-avatar ${NODE_TONE[active.node] ?? "mint"}`}>
                  <Icon name="i-box" />
                </span>
                <div>
                  <div className="name">{guestLabel(active)}</div>
                  <div className="sub">
                    {active.node || "—"} · vmid {active.vmid}
                  </div>
                </div>
                <span
                  className={`status ${active.status === "running" ? "healthy" : "down"}`}
                  style={{ marginLeft: "auto" }}
                >
                  <span className={`dot ${active.status === "running" ? "mint" : "coral"}`} /> {active.status}
                </span>
              </div>

              <div className="kv">
                <div>
                  <div className="k">Status</div>
                  <div className="v">{active.status}</div>
                </div>
                <div>
                  <div className="k">Baseline</div>
                  <div className="v">{active.sejak || "—"}</div>
                </div>
                <div>
                  <div className="k">Guest agent</div>
                  <div className="v" style={{ fontSize: 11 }}>
                    {active.agent_ok ? "qga responding" : "qga silent"}
                  </div>
                </div>
                <div>
                  <div className="k">Agent failures</div>
                  <div className="v" style={{ fontSize: 11 }}>
                    {active.agent_gagal ? `${active.agent_gagal}×` : "0"}
                  </div>
                </div>
                <div>
                  <div className="k">Node</div>
                  <div className="v" style={{ fontSize: 11 }}>
                    {active.node || "—"}
                  </div>
                </div>
                <div>
                  <div className="k">Last action</div>
                  <div className="v" style={{ fontSize: 11, fontFamily: "var(--sans)" }}>
                    {active.last_action ? `${active.last_action.aksi} · ${timeOf(active.last_action.ts)}` : "—"}
                  </div>
                </div>
              </div>

              <div>
                <div className="sect-title">Healer decisions untuk guest ini</div>
                <div className="event-list">
                  {data?.decisions.some((decision) => decision.vmid === active.vmid) ? (
                    data.decisions
                      .filter((decision) => decision.vmid === active.vmid)
                      .slice(0, 4)
                      .map((decision, index) => (
                        <div className="event" key={`${decision.ts}-${index}`}>
                          <div className="event-rail">
                            <span className="event-dot mint" />
                          </div>
                          <div className="event-body">
                            <div className="t">
                              {decision.aksi} → {decision.hasil}
                            </div>
                            <div className="m">
                              {timeOf(decision.ts)} · sumber={decision.sumber} · {decision.alasan.slice(0, 90)}
                            </div>
                          </div>
                        </div>
                      ))
                  ) : (
                    <div className="tiny dim">Tidak ada decision untuk vmid ini di log terakhir.</div>
                  )}
                </div>
              </div>

              <div className="ro-note">
                <Icon name="i-lock" className="icon sm" />
                <span>
                  UI ini <b>read-only</b>. Tindakan hanya lewat loop healer (gate deterministik) atau SSH
                  manual — tidak ada endpoint aksi dari HTTP.
                </span>
              </div>

              <details className="json">
                <summary>Raw state object</summary>
                <pre>{JSON.stringify(active, null, 2)}</pre>
              </details>
            </>
          ) : (
            <Empty>Pilih guest dari tabel.</Empty>
          )}
        </div>
        <div className="drawer-foot">
          <CopyButton text={inspectCommand} label="Copy inspect cmd" />
          <CopyButton text={active ? JSON.stringify(active, null, 2) : ""} label="Copy JSON" />
        </div>
      </aside>
    </>
  );
}
