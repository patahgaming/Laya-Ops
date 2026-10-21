import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { ErrorState } from "./components/ui";
import { useAuth } from "./state/auth";
import { FleetPage } from "./pages/FleetPage";
import { GoalsPage } from "./pages/GoalsPage";
import { HealerPage } from "./pages/HealerPage";
import { IncidentsPage } from "./pages/IncidentsPage";
import { LoginPage } from "./pages/LoginPage";
import { OverviewPage } from "./pages/OverviewPage";
import { RawPage } from "./pages/RawPage";

function Splash() {
  return (
    <div className="auth-page">
      <div className="auth-stage">
        <div className="empty">
          <span className="spinner" aria-hidden="true" /> menghubungkan ke Laya Ops API…
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const { loading, info, error, reload } = useAuth();

  if (loading) return <Splash />;
  if (!info) {
    return (
      <div className="auth-page">
        <div className="auth-stage" style={{ width: "min(720px, 100%)" }}>
          <ErrorState message={error ?? "auth config tidak tersedia"} onRetry={() => void reload()} />
        </div>
      </div>
    );
  }

  const authenticated = info.mode === "off" || Boolean(info.user);

  return (
    <Routes>
      <Route path="/login" element={authenticated ? <Navigate to="/" replace /> : <LoginPage />} />
      <Route element={authenticated ? <AppShell /> : <Navigate to="/login" replace />}>
        <Route index element={<OverviewPage />} />
        <Route path="fleet" element={<FleetPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="healer" element={<HealerPage />} />
        <Route
          path="goals"
          element={info.features.goals ? <GoalsPage /> : <Navigate to="/" replace />}
        />
        <Route path="raw" element={<RawPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
