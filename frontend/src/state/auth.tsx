import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "../data/api";
import type { AuthInfo } from "../data/types";

interface AuthState {
  loading: boolean;
  info: AuthInfo | null;
  error: string | null;
  login: (password: string) => Promise<void>;
  logout: () => Promise<void>;
  reload: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({
  loading: true,
  info: null,
  error: null,
  login: async () => undefined,
  logout: async () => undefined,
  reload: async () => undefined
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<AuthInfo | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    try {
      setInfo(await api.get<AuthInfo>("/api/auth/config"));
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const login = useCallback(
    async (password: string) => {
      await api.post<AuthInfo>("/api/auth/login", { password });
      await reload();
    },
    [reload]
  );

  const logout = useCallback(async () => {
    await api.post("/api/auth/logout");
    await reload();
  }, [reload]);

  const value = useMemo(
    () => ({ loading, info, error, login, logout, reload }),
    [loading, info, error, login, logout, reload]
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
