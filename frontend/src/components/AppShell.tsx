import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { clockOf } from "../data/format";
import type { Status } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../state/auth";
import { useRefresh } from "../state/refresh";
import { Icon } from "./Icon";

const SECTION_LABEL: Record<string, string> = {
  "/": "overview",
  "/fleet": "fleet",
  "/incidents": "incidents",
  "/healer": "healer",
  "/raw": "raw data"
};

const NAV_GROUPS = [
  {
    label: "Plane",
    items: [
      { to: "/", label: "Overview", icon: "i-grid", end: true },
      { to: "/fleet", label: "Fleet", icon: "i-layers", countKey: "guests" },
      { to: "/incidents", label: "Incidents", icon: "i-bell", badgeKey: "alerts" }
    ]
  },
  {
    label: "Control",
    items: [
      { to: "/healer", label: "Healer", icon: "i-sliders" },
      { to: "/raw", label: "Raw data", icon: "i-activity" }
    ]
  }
] as const;

export function AppShell() {
  const { info, logout } = useAuth();
  const { refresh } = useRefresh();
  const location = useLocation();
  const navigate = useNavigate();
  const { data: status } = useApi<Status>("/api/status", 20_000);
  const [now, setNow] = useState(() => new Date());
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const section = SECTION_LABEL[location.pathname] ?? "console";
    document.title = `${section[0].toUpperCase()}${section.slice(1)} · Laya Ops`;
  }, [location.pathname]);

  const name = info?.user?.name ?? "operator";
  const initials = name
    .split(/[\s._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  const guestsTotal = status?.summary.total;
  const alertsFiring = status?.alerts.instances;

  const signOut = async () => {
    setBusy(true);
    try {
      await logout();
      navigate("/login", { replace: true });
    } finally {
      setBusy(false);
    }
  };

  const counts = { guests: guestsTotal, alerts: alertsFiring };

  return (
    <div className="app">
      <aside className="sidebar">
        <NavLink className="brand" to="/">
          <span className="brand-mark">
            <Icon name="i-logo" />
          </span>
          <span className="brand-name">
            laya <span>ops</span>
          </span>
        </NavLink>

        <nav className="nav">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              <div className="nav-label">{group.label}</div>
              {group.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={"end" in item ? item.end : false}
                  className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
                >
                  <Icon name={item.icon} />
                  <span>{item.label}</span>
                  {"countKey" in item && counts[item.countKey as "guests"] != null ? (
                    <span className="nav-count">{counts.guests}</span>
                  ) : null}
                  {"badgeKey" in item && counts[item.badgeKey as "alerts"] != null ? (
                    <span className="nav-badge">{counts.alerts}</span>
                  ) : null}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>

        <div className="sidebar-foot">
          <div className="plane-card">
            <div className="plane-card-top">
              <span className="dot mint pulse" /> VM105 · monitor
            </div>
            <div className="plane-card-meta mono">10.10.0.107 · hq1</div>
            <div className="plane-card-foot">
              <span>healer state</span>
              <span>{status ? `${status.summary.running}/${status.summary.total} running` : "—"}</span>
            </div>
          </div>
          <div className="user">
            <span className="avatar">{initials || "OP"}</span>
            <span>
              <span className="user-name">{name}</span>
              <span className="user-role" style={{ display: "block", textTransform: "capitalize" }}>
                {info?.mode === "off" ? "LAN access" : info?.provider ?? "operator"}
              </span>
            </span>
            <button
              type="button"
              className="btn-icon"
              title="Logout"
              aria-label="Logout"
              disabled={busy}
              onClick={() => void signOut()}
              style={{ marginLeft: "auto" }}
            >
              <Icon name="i-logout" className="icon sm" />
            </button>
          </div>
        </div>
      </aside>

      <div className="main">
        <header className="topbar">
          <div className="crumb">
            <span>hq1</span>
            <span className="sep">/</span>
            <span className="mono">monitor</span>
            <span className="sep">/</span>
            <span className="here">{SECTION_LABEL[location.pathname] ?? "console"}</span>
          </div>
          <div className="topbar-actions">
            <span className="live-pill">
              <span className="dot mint pulse" />
              LIVE · API <b className="mono">{clockOf(now)}</b>
            </span>
            <button type="button" className="btn-icon" title="Refresh" aria-label="Refresh" onClick={refresh}>
              <Icon name="i-refresh" />
            </button>
            <span className="tiny dim mono">
              {status?.degraded ? "degraded upstream" : status ? "all sources ok" : "connecting…"}
            </span>
          </div>
        </header>

        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
