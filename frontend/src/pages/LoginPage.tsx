import { useState, type CSSProperties, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { errorMessage } from "../data/api";
import { Icon } from "../components/Icon";
import { useAuth } from "../state/auth";

const SATELLITES = [
  { tone: "s-orange", icon: "i-torch", radius: 136, angle: -96 },
  { tone: "s-amber", icon: "i-flame", radius: 136, angle: 24 },
  { tone: "s-orange", icon: "i-bell", radius: 136, angle: 144 },
  { tone: "s-violet", icon: "i-box", radius: 192, angle: -36 },
  { tone: "s-blue", icon: "i-wheel", radius: 192, angle: 100 },
  { tone: "s-coral", icon: "i-key", radius: 192, angle: 208 }
];

export function LoginPage() {
  const { info, loading, login } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="auth-page">
        <div className="auth-stage">
          <div className="empty">
            <span className="spinner" aria-hidden="true" /> memeriksa sesi…
          </div>
        </div>
      </div>
    );
  }
  if (info && (info.mode === "off" || info.user)) {
    return <Navigate to="/" replace />;
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      await login(password);
      navigate("/", { replace: true });
    } catch (err) {
      setFormError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const passwordMode = info?.mode === "password";
  const oidcMode = info?.mode === "oidc";
  const plane = info?.plane;

  return (
    <div className="auth-page">
      <header className="auth-top">
        <a className="brand" href="/">
          <span className="brand-mark">
            <Icon name="i-logo" />
          </span>
          <span className="brand-name">
            laya <span>ops</span>
          </span>
        </a>
        <div className="status-chip">
          <span className="dot mint pulse" /> read-only console
          {plane?.name ? <b>{plane.name}</b> : null}
        </div>
      </header>

      <main className="auth-stage">
        <section className="auth-card" aria-label="Sign in">
          <div className="auth-form">
            <div className="auth-eyebrow">
              <span className="line" />
              <span className="eyebrow">Plane monitoring &amp; self-healing</span>
            </div>

            <h1 className="auth-title">
              Sign in to the <em>plane</em>.
            </h1>
            <p className="auth-sub">
              Laya reads the healer API and Prometheus, then shows what the plane did on its own. No
              write path, no remote shell — read-only by design.
            </p>

            {oidcMode ? (
              <form onSubmit={(event) => event.preventDefault()}>
                <button
                  className="sso-btn"
                  type="button"
                  onClick={() => info?.login_url && window.location.assign(info.login_url)}
                >
                  <Icon name="i-key" /> Continue with Keycloak <span className="kbd">SSO</span>
                </button>
                <div className="auth-note" style={{ paddingTop: 18 }}>
                  <Icon name="i-shield" className="icon sm" />
                  <span>
                    Login memakai Keycloak realm sekolah. Bila IdP down, akses console lewat SSH /
                    tunnel tetap tersedia.
                  </span>
                </div>
              </form>
            ) : null}

            {passwordMode ? (
              <form onSubmit={submit}>
                <div className="field">
                  <label htmlFor="password">Operator password</label>
                  <div className="input-wrap">
                    <Icon name="i-lock" />
                    <input
                      className="input"
                      id="password"
                      type="password"
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      autoComplete="current-password"
                      required
                    />
                  </div>
                </div>

                {formError ? (
                  <div className="auth-error" role="alert">
                    <Icon name="i-alert-triangle" className="icon sm" /> {formError}
                  </div>
                ) : null}

                <button className="btn btn-block" type="submit" disabled={busy || !password} style={{ height: 44 }}>
                  {busy ? "Signing in…" : "Sign in"} <Icon name="i-arrow-right" />
                </button>
              </form>
            ) : null}

            <div className="auth-modebox">
              <div>
                <span className="k">auth mode</span>
                <span className="v">{info?.provider ?? "none"}</span>
              </div>
              <div>
                <span className="k">session</span>
                <span className="v">8h · HttpOnly</span>
              </div>
            </div>

            <div className="auth-note">
              <Icon name="i-shield" />
              <span>
                Console ini read-only: tidak ada endpoint aksi, ack, atau silence. Tindakan hanya lewat
                loop healer / SSH.
              </span>
            </div>
          </div>

          <div className="auth-visual" aria-hidden="true">
            <div className="visual-head">
              <span className="dot mint" /> Monitoring plane
              {plane ? (
                <span className="right mono">
                  {plane.site}
                  {plane.name ? ` · ${plane.name.toLowerCase()}` : ""}
                </span>
              ) : null}
            </div>

            <div className="orbit">
              <div className="orbit-layer ring-1" />
              <div className="orbit-layer ring-2" />
              <div className="orbit-core">
                <Icon name="i-logo" />
              </div>
              {SATELLITES.map((satellite) => (
                <div
                  key={satellite.icon}
                  className={`sat ${satellite.tone}`}
                  style={
                    {
                      "--r": `${satellite.radius}px`,
                      "--a": `${satellite.angle}deg`
                    } as CSSProperties
                  }
                >
                  <Icon name={satellite.icon} />
                </div>
              ))}
            </div>

            <div className="visual-foot">
              <div className="visual-caption">
                <span className="dot" /> prometheus <span className="dot" /> grafana <span className="dot" />{" "}
                alertmanager <span className="dot" /> proxmox <span className="dot" /> k3s <span className="dot" />{" "}
                keycloak
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="auth-foot">
        <span>© 2026 {info?.app_name ?? "Laya Ops"} · internal tooling</span>
        <span className="right">
          {plane ? <span>{[plane.site, plane.name, plane.host].filter(Boolean).join(" · ")}</span> : null}
          {info?.app_version ? <span>build {info.app_version}</span> : null}
        </span>
      </footer>
    </div>
  );
}
