import { useEffect, useRef, useState } from "react";
import { ApiError, api, errorMessage } from "../data/api";
import { useRefresh } from "../state/refresh";

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
}

/**
 * Poll a same-origin JSON endpoint. The global refresh counter (topbar / page
 * buttons) also re-triggers the request immediately.
 */
export function useApi<T>(path: string | null, intervalMs = 15_000): UseApiResult<T> {
  const { version, markUpdated } = useRefresh();
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const started = useRef(false);

  useEffect(() => {
    if (!path) return;
    let alive = true;
    if (!started.current) setLoading(true);

    const run = async () => {
      try {
        const next = await api.get<T>(path);
        if (!alive) return;
        setData(next);
        setError(null);
        started.current = true;
        markUpdated(new Date());
      } catch (err) {
        if (!alive) return;
        setError(errorMessage(err));
        if (err instanceof ApiError && err.status === 401) {
          window.location.assign("/login");
        }
      } finally {
        if (alive) setLoading(false);
      }
    };

    void run();
    const timer = window.setInterval(run, intervalMs);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [path, intervalMs, version, markUpdated]);

  return { data, error, loading };
}
