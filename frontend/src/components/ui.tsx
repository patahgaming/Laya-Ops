import type { CSSProperties, ReactNode } from "react";
import { Icon } from "./Icon";
import { useToast } from "../state/toast";

export type Tone = "mint" | "amber" | "coral" | "blue" | "violet" | "neutral";

export function Pill({
  tone = "neutral",
  dot,
  children,
  className = "",
  style
}: {
  tone?: Tone;
  dot?: Tone;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <span className={`pill ${tone} ${className}`.trim()} style={style}>
      {dot ? <span className={`dot ${dot}`} /> : null}
      {children}
    </span>
  );
}

export function Panel({
  title,
  sub,
  right,
  children,
  className = "",
  body = false
}: {
  title: ReactNode;
  sub?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  body?: boolean;
}) {
  return (
    <section className={`panel ${className}`.trim()}>
      <div className="panel-head">
        <div>
          <div className="panel-title">{title}</div>
          {sub ? <div className="panel-sub">{sub}</div> : null}
        </div>
        {right ? <div className="right">{right}</div> : null}
      </div>
      {body ? <div className="panel-body">{children}</div> : children}
    </section>
  );
}

export function Meter({ segments }: { segments: Array<[string, number]> }) {
  const total = segments.reduce((sum, [, value]) => sum + value, 0) || 1;
  return (
    <div className="meter">
      {segments
        .filter(([, value]) => value > 0)
        .map(([tone, value], index) => (
          <i key={`${tone}-${index}`} className={tone} style={{ width: `${(value / total) * 100}%` }} />
        ))}
    </div>
  );
}

export function KpiCard({
  icon,
  label,
  value,
  of,
  unit,
  note,
  pill,
  meter
}: {
  icon: string;
  label: string;
  value: ReactNode;
  of?: ReactNode;
  unit?: string;
  note: ReactNode;
  pill?: ReactNode;
  meter?: ReactNode;
}) {
  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-ico">
          <Icon name={icon} />
        </span>
        <span className="kpi-label">{label}</span>
        {pill}
      </div>
      <div className="kpi-value">
        {value}
        {of ? <span className="of">/{of}</span> : null}
        {unit ? <span className="unit">{unit}</span> : null}
      </div>
      <div className="kpi-note">{note}</div>
      {meter}
    </div>
  );
}

export function PageHead({
  eyebrow,
  title,
  sub,
  actions
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  sub?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-head">
      <div>
        <div className="eyebrow" style={{ marginBottom: 8 }}>
          {eyebrow}
        </div>
        <h1>{title}</h1>
        {sub ? <p className="sub">{sub}</p> : null}
      </div>
      {actions ? <div className="head-actions">{actions}</div> : null}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorState({
  message,
  onRetry,
  title = "Gagal memuat data"
}: {
  message: string;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div className="banner crit" role="alert">
      <div className="banner-ico">
        <Icon name="i-alert-triangle" className="icon lg" />
      </div>
      <div className="banner-body">
        <div className="banner-title">{title}</div>
        <div className="banner-sub mono">{message}</div>
      </div>
      {onRetry ? (
        <div className="banner-actions">
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            <Icon name="i-refresh" className="icon sm" /> Retry
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function LoadingPanel({ label = "memuat…" }: { label?: string }) {
  return (
    <div className="panel">
      <div className="empty">
        <span className="spinner" aria-hidden="true" /> {label}
      </div>
    </div>
  );
}

export function CopyButton({ text, label }: { text: string; label: string }) {
  const toast = useToast();
  return (
    <button
      type="button"
      className="btn btn-sm"
      onClick={() => {
        void navigator.clipboard
          .writeText(text)
          .then(() => toast("Copied to clipboard"))
          .catch(() => toast("Clipboard tidak tersedia"));
      }}
    >
      <Icon name="i-copy" className="icon sm" /> {label}
    </button>
  );
}
