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
  detail?: string | null;
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
  menunggu_persetujuan: number;
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
  jenis: string;
  tingkat: string;
  izin: string;
  jenis_guest: string;
  status: string;
  agent: boolean | null;
  oleh: string;
  state: string;
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

export interface MetricCounter {
  labels: Record<string, string>;
  value: number;
}

export interface Metrics {
  healer_up: number | null;
  healer_dry: number | null;
  pending: number | null;
  action_totals: MetricCounter[];
  incident_totals: MetricCounter[];
  approval_totals: MetricCounter[];
  escalation_total: number | null;
  k8s_action_totals: MetricCounter[];
  k8s_escalation_totals: MetricCounter[];
  node_failures: MetricCounter[];
}

export interface PushedAlert {
  alertname: string;
  severity: string;
  status: string;
  summary: string;
  description: string;
  starts_at: string;
  ends_at: string;
  fingerprint: string;
  labels: Record<string, string>;
}

export interface PendingApproval {
  vmid: number | null;
  nama: string;
  node: string;
  jenis: string;
  jenis_guest: string;
  status: string;
  aksi: string;
  sumber: string;
  alasan: string;
  diminta: string;
  kedaluwarsa: string;
  seconds_left: number | null;
  approved: boolean;
  approved_at: string;
  oleh: string;
}

export interface PendingResponse {
  generated_at: string;
  ok: boolean;
  count: number;
  pending: PendingApproval[];
}

export interface ClassifierHealth {
  configured: boolean;
  ok: boolean;
  model: string;
  ms: number;
  error?: string | null;
}

export interface EngineDecision {
  ts: string;
  time: string;
  jenis: string;
  target: string;
  kelas: string;
  keterangan: string;
  confidence: number | null;
  aksi: string;
  hasil: string;
  dry_run: boolean;
  error: string;
}

export interface EngineHealer {
  configured: boolean;
  ok: boolean;
  ms: number;
  error?: string | null;
  decisions: EngineDecision[];
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
    pushed: PushedAlert[];
    pushed_ok: boolean;
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
  pushed: PushedAlert[];
  pushed_ok: boolean;
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
  MINOR_ACTIONS?: string[];
  IZIN_TTL?: number;
  K8S_NS?: string[];
  LLM_MODEL?: string;
  LLM_AKTIF?: boolean;
  NODES?: Record<string, string>;
}

export interface KnobsResponse {
  generated_at: string;
  links: Record<string, string>;
  knobs: Knobs;
  metrics: Metrics;
  last_decision: Decision | null;
  summary: Summary;
  pending: PendingApproval[];
  pending_ok: boolean;
  classifier: ClassifierHealth;
  engine: EngineHealer;
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
