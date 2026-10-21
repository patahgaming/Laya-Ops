export type AuthMode = "off" | "password" | "oidc";

export interface AuthUserInfo {
  name: string;
  email?: string;
  method?: string;
}

export interface PlaneInfo {
  name: string;
  site: string;
  host: string;
  ssh_user: string;
}

export interface AuthInfo {
  mode: AuthMode;
  user: AuthUserInfo | null;
  provider: string;
  login_url?: string | null;
  app_name: string;
  app_version: string;
  plane: PlaneInfo;
}

export interface SourceStatus {
  name: string;
  url: string;
  ok: boolean;
  ms: number;
  error?: string | null;
}

export interface Targets {
  up: number;
  total: number;
  down: number;
  error?: string | null;
}

export interface Summary {
  total: number;
  running: number;
  stopped: number;
  insiden_24h: number;
  aksi_24h: number;
  pulih_24h: number;
  eskalasi_24h: number;
  dry: boolean;
  targets: Targets;
}

export interface Decision {
  ts: string;
  time: string;
  target: string;
  aksi: string;
  sumber: string;
  hasil: string;
  alasan: string;
  ket: string;
  vmid: number | null;
  nama: string | null;
  node: string | null;
  dry: boolean;
}

export interface Guest {
  vmid: number;
  name: string | null;
  node: string;
  status: string;
  sejak: string;
  agent_ok: boolean;
  agent_gagal: number;
  last_action: Decision | null;
}

export interface Guests {
  total: number;
  running: number;
  stopped: number;
  nodes: Record<string, number>;
  guests: Guest[];
}

export interface Job {
  job: string;
  up: number;
  down: number;
}

export interface Runbook {
  note: string;
  lines: string[];
}

export type Severity = "critical" | "warning" | "info" | "none";

export interface AlertGroup {
  name: string;
  severity: Severity;
  instances: number;
  namespaces: string[];
  jobs: string[];
  oldest_seconds: number | null;
  runbook: Runbook;
}

export interface AlertCounts {
  critical: number;
  warning: number;
  info: number;
  none: number;
}

export interface Metrics {
  healer_up: number | null;
  healer_dry: number | null;
}

export interface Overview {
  generated_at: string;
  degraded: boolean;
  links: Record<string, string>;
  summary: Summary;
  guests: Guests;
  alerts: {
    ok: boolean;
    instances: number;
    counts: AlertCounts;
    groups: AlertGroup[];
  };
  jobs: Job[];
  decisions: Decision[];
  endpoints: SourceStatus[];
  metrics: Metrics;
}

export interface Status {
  generated_at: string;
  ok: boolean;
  degraded: boolean;
  summary: Summary;
  alerts: { instances: number; counts: AlertCounts };
  jobs_down: number;
  healer_up: number | null;
}

export interface GuestsResponse {
  generated_at: string;
  guests: Guests;
  decisions: Decision[];
}

export interface AlertsResponse {
  generated_at: string;
  ok: boolean;
  instances: number;
  counts: AlertCounts;
  groups: AlertGroup[];
  links: Record<string, string>;
}

export interface DecisionsResponse {
  generated_at: string;
  decisions: Decision[];
}

export interface Knobs {
  AUTO_IDS?: number[];
  PROTECT?: number[];
  MAX_AKSI?: number;
  COOLDOWN?: number;
  INTERVAL?: number;
  DRY_RUN?: boolean;
  K8S_NS?: string[];
  LLM_MODEL?: string;
  LLM_AKTIF?: boolean;
  NODES?: Record<string, string>;
}

export interface KnobsResponse {
  generated_at: string;
  knobs: Knobs;
  metrics: Metrics;
  last_decision: Decision | null;
  summary: Summary;
}

export interface RawSource {
  ok: boolean;
  ms: number;
  url: string;
  error?: string | null;
  value: unknown;
}

export type RawResponse = Record<string, RawSource>;

export interface HourBucket {
  label: string;
  total: number;
  escalated: number;
}
