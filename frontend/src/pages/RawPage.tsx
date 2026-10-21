import { useState } from "react";
import { Icon } from "../components/Icon";
import { CopyButton, Empty, ErrorState, PageHead, Panel, Pill } from "../components/ui";
import type { RawResponse } from "../data/types";
import { useApi } from "../hooks/useApi";
import { useRefresh } from "../state/refresh";
import { useToast } from "../state/toast";

const SOURCES = "summary,state,knobs,decisions,alerts,jobs";

export function RawPage() {
  const { data, error, loading } = useApi<RawResponse>(`/api/raw?sources=${SOURCES}`, 30_000);
  const { refresh } = useRefresh();
  const toast = useToast();
  const [selected, setSelected] = useState<string | null>(null);

  const names = data ? Object.keys(data) : [];
  const active = selected && data?.[selected] ? selected : names[0] ?? null;
  const current = active && data ? data[active] : null;
  const text = current ? JSON.stringify(current.value, null, 2) : "";

  return (
    <>
      <PageHead
        eyebrow="Raw data · payload upstream apa adanya"
        title="Raw data"
        sub="Respons mentah dari healer API, Prometheus (lewat proxy backend) dan /metrics. Dipakai untuk debugging UI maupun integrasi."
        actions={
          <>
            <button type="button" className="btn" onClick={refresh}>
              <Icon name="i-refresh" /> Refresh
            </button>
            {current ? <CopyButton text={text} label={`Copy ${active}`} /> : null}
          </>
        }
      />

      {error && !data ? <ErrorState message={error} onRetry={refresh} /> : null}

      <Panel
        title="Upstream payload"
        sub={data ? `${names.length} sources · read-only` : "memuat payload…"}
        right={<Pill>read-only</Pill>}
      >
        {loading && !data ? (
          <div className="empty">
            <span className="spinner" aria-hidden="true" /> memuat payload mentah…
          </div>
        ) : names.length === 0 ? (
          <Empty>Tidak ada data.</Empty>
        ) : (
          <>
            <div className="raw-tabs">
              {names.map((name) => {
                const source = data?.[name];
                return (
                  <button
                    key={name}
                    type="button"
                    className={`chip${active === name ? " active" : ""}`}
                    onClick={() => setSelected(name)}
                  >
                    {name}
                    {source ? (
                      <span
                        className="tiny"
                        style={{ marginLeft: 6, color: source.ok ? "var(--mint)" : "var(--coral)" }}
                      >
                        {source.ok ? `${source.ms}ms` : "fail"}
                      </span>
                    ) : null}
                  </button>
                );
              })}
            </div>
            <div className="panel-body" style={{ paddingTop: 12 }}>
              <div className="copy-command">
                <div className="code-block raw-json">{text || "—"}</div>
                {current ? (
                  <button
                    type="button"
                    className="copy-btn"
                    aria-label="Copy JSON"
                    onClick={() => {
                      void navigator.clipboard
                        .writeText(text)
                        .then(() => toast("JSON copied"))
                        .catch(() => toast("Clipboard tidak tersedia"));
                    }}
                  >
                    <Icon name="i-copy" />
                  </button>
                ) : null}
              </div>
              {current && !current.ok ? (
                <div className="ro-note" style={{ marginTop: 12 }}>
                  <Icon name="i-alert-triangle" className="icon sm" />
                  <span>
                    Sumber ini gagal: <span className="mono">{current.error ?? "unknown"}</span>.
                  </span>
                </div>
              ) : null}
            </div>
          </>
        )}
      </Panel>
    </>
  );
}
