export type AuthMode = "off" | "password" | "oidc";

export interface AuthUserInfo {
  name: string;
  email?: string;
  method?: string;
  sub?: string;
  groups?: string[];
}

export interface FeatureFlags {
  goals: boolean;
  goals_execute: boolean;
  goals_llm: boolean;
  password_single_person: boolean;
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
  csrf_token: string;
  features: FeatureFlags;
  can_approve: boolean;
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
  goal_24h: number;
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

/* ---------- AI goals ---------- */

export type GoalStatus =
  | "pending_approval"
  | "approved"
  | "dispatching"
  | "executing"
  | "succeeded"
  | "failed"
  | "unknown"
  | "rejected"
  | "cancelled"
  | "expired";

export type GoalAction =
  | "start"
  | "resume"
  | "reset"
  | "rollout_undo"
  | "noop"
  | "escalate";
export type GoalRisk = "low" | "medium" | "high";
export type GoalTargetKind = "proxmox_guest" | "k8s_deployment";

export interface GoalTemplateVariable {
  name: string;
  type: string;
  required: boolean;
  max_length: number | null;
  enum: string[];
  default: unknown;
  description: string;
}

export interface ManualGoalSecret {
  name: string;
  description: string;
}

export interface GoalTemplate {
  id: string;
  version: string;
  name: string;
  description: string;
  target_kind: string;
  actions: string[];
  max_steps: number;
  variables: GoalTemplateVariable[];
  manual_secrets: ManualGoalSecret[];
  execution_enabled: boolean;
}

export interface GoalTemplatesResponse {
  templates: GoalTemplate[];
}

/** Target of a Proxmox guest plan step. */
export interface GuestPlanTarget {
  vmid: number;
  name: string;
  node: string;
  guest_type: "vm" | "ct";
  status: string;
}

/** Target of a Deployment rollback. Kept separate so a guest plan can never
 * carry k8s fields and vice versa. */
export interface K8sPlanTarget {
  namespace: string;
  deployment: string;
  revision: number;
  previous_revision: number;
  status: string;
  replicas: number;
  available: number;
  images: string[];
  previous_images: string[];
}

export type GoalPlanTarget = GuestPlanTarget | K8sPlanTarget;

export interface GoalPlanStep {
  step_id: string;
  action: GoalAction;
  target: GoalPlanTarget;
  params: Record<string, unknown>;
  expected_effect: string;
  risk: GoalRisk;
  requires_approval: boolean;
}

export interface GoalPlan {
  template_id: string;
  template_version: string;
  target_kind?: string;
  goal: string;
  target: GoalPlanTarget;
  variables: Record<string, unknown>;
  steps: GoalPlanStep[];
  rationale: string;
  warnings: string[];
  generated_by: "rules" | "llm";
  evidence_hash: string;
}

export interface GoalTargetSummary {
  vmid?: number;
  name?: string;
  node?: string;
  guest_type?: string;
  status?: string;
  auto?: boolean;
  namespace?: string;
  deployment?: string;
  revision?: number;
  previous_revision?: number;
  replicas?: number;
  available?: number;
  images?: string[];
  previous_images?: string[];
}

/** Row returned by GET /api/goals/targets for a guest template. */
export interface GoalGuestTargetOption {
  vmid: number;
  name: string;
  node: string;
  guest_type: string;
  status: string;
  auto: boolean;
  protected: boolean;
}

/** Row returned by GET /api/goals/targets for a k8s template. */
export interface GoalK8sTargetOption {
  namespace: string;
  deployment: string;
  revision: number;
  previous_revision: number;
  status: string;
  replicas: number;
  available: number;
  images: string[];
  previous_images: string[];
  ok: boolean;
  allowed: boolean;
  protected: boolean;
}

export type GoalTargetOption = GoalGuestTargetOption | GoalK8sTargetOption;

export interface GoalTargetsResponse {
  template_id: string;
  target_kind: string;
  targets: GoalTargetOption[];
  error: string;
}

export interface GoalPreviewResponse {
  preview_id: string;
  status: "ready" | "needs_input" | "blocked";
  plan: GoalPlan;
  plan_hash: string;
  warnings: string[];
  missing: string[];
  blocked_reason: string;
  expires_at: string;
}

export interface ApprovalRequirements {
  approval_code: boolean;
  confirm: boolean;
  high_risk: boolean;
  passphrase_required: boolean;
  typed_confirmation: string;
}

export interface GoalRun {
  id: string;
  goal_id: string;
  plan_id: string;
  status: string;
  claimed_at: string;
  request_sent_at: string;
  accepted_at: string;
  started_at: string;
  finished_at: string;
  heartbeat_at: string;
  last_polled_at: string;
  lease_owner: string;
  lease_expires_at: string;
  result: Record<string, unknown> | null;
  error: string;
  error_code: string;
  dry_run: boolean;
  attempts: number;
}

export interface GoalView {
  id: string;
  status: GoalStatus;
  template_id: string;
  template_version: string;
  target: GoalTargetSummary;
  goal: string;
  variables: Record<string, unknown>;
  plan: GoalPlan;
  plan_hash: string;
  evidence_hash: string;
  warnings: string[];
  requested_by: string;
  requested_by_sub: string;
  requested_at: string;
  expires_at: string;
  approved_by: string;
  approved_at: string;
  rejected_by: string;
  rejected_at: string;
  reject_reason: string;
  execute_before: string;
  execute_by: string;
  execute_requested_at: string;
  execute_count: number;
  target_kind: string;
  run: GoalRun | null;
  result: Record<string, unknown> | null;
  error: string;
  created_at: string;
  updated_at: string;
  can_approve: boolean;
  can_execute: boolean;
  can_reconcile: boolean;
  approval_mode: string;
  execution_enabled: boolean;
  high_risk: boolean;
  requirements: ApprovalRequirements;
}

export interface GoalCreated extends GoalView {
  approval_code: string | null;
  idempotent_replay: boolean;
}

export interface GoalListResponse {
  goals: GoalView[];
  next_cursor: string | null;
}

export interface GoalAuditEntry {
  ts: string;
  goal_id: string;
  actor: string;
  actor_sub: string;
  actor_method: string;
  event: string;
  detail: Record<string, unknown>;
  client_ip: string;
  user_agent: string;
}

export interface GoalAuditResponse {
  goal_id: string;
  events: GoalAuditEntry[];
}

export interface GoalActionResponse {
  ok: boolean;
  goal: GoalView;
  message: string;
  accepted: boolean;
}
