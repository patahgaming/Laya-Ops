import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

interface RefreshState {
  version: number;
  refresh: () => void;
  lastUpdated: Date | null;
  markUpdated: (date: Date) => void;
}

const RefreshContext = createContext<RefreshState>({
  version: 0,
  refresh: () => undefined,
  lastUpdated: null,
  markUpdated: () => undefined
});

export function RefreshProvider({ children }: { children: ReactNode }) {
  const [version, setVersion] = useState(0);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  const markUpdated = useCallback((date: Date) => setLastUpdated(date), []);
  const value = useMemo(
    () => ({ version, refresh, lastUpdated, markUpdated }),
    [version, refresh, lastUpdated, markUpdated]
  );
  return <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>;
}

export function useRefresh(): RefreshState {
  return useContext(RefreshContext);
}
