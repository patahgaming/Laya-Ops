import { Icon } from "./Icon";
import { CopyButton, Pill } from "./ui";
import { guestLabel } from "../data/format";
import { goalRiskTone } from "../data/goals";
import type { GoalPlan } from "../data/types";

function shortHash(value?: string | null): string {
  return value ? `${value.slice(0, 16)}…` : "—";
}

export function GoalPlanView({
  plan,
  planHash = "",
  warnings
}: {
  plan?: GoalPlan | null;
  planHash?: string;
  warnings?: string[];
}) {
  if (!plan) {
    return <div className="empty">Plan belum tersedia.</div>;
  }
  const step = plan.steps?.[0];
  const target = step?.target ?? plan.target;
  if (!target) {
    return <div className="empty">Plan tidak memiliki target.</div>;
  }
  const action = step?.action ?? "noop";
  const risk = step?.risk ?? "low";
  const shownWarnings = warnings?.length ? warnings : plan.warnings ?? [];
  const params = step && Object.keys(step.params ?? {}).length ? JSON.stringify(step.params) : "—";

  return (
    <div className="goal-plan">
      <div className="goal-plan-head">
        <div className="cell-agent">
          <span
            className={`agent-avatar ${
              target.guest_type === "ct" ? "violet" : target.status === "running" ? "mint" : "amber"
            }`}
          >
            <Icon name={target.guest_type === "ct" ? "i-box" : "i-server"} />
          </span>
          <div>
            <div className="agent-name">{guestLabel(target)}</div>
            <div className="agent-sub">
              #{target.vmid} · {target.node || "—"} · {target.guest_type}
            </div>
          </div>
        </div>
        <div className="goal-plan-pills">
          <Pill tone="blue">{action}</Pill>
          <Pill tone={goalRiskTone(risk)}>{risk} risk</Pill>
          <Pill tone={target.status === "running" ? "mint" : "amber"}>{target.status}</Pill>
          <Pill tone={plan.generated_by === "llm" ? "violet" : "neutral"}>{plan.generated_by}</Pill>
        </div>
      </div>

      {plan.goal ? <p className="goal-quote">“{plan.goal}”</p> : null}

      <div className="pipeline goal-pipeline">
        <div className="pipe-step active">
          <span className="pipe-num">01</span>
          <div>
            <div className="pipe-title">
              {action} → {step?.expected_effect || "running"}
            </div>
            <div className="pipe-desc">
              {step?.requires_approval === false
                ? "Tidak butuh approval langkah."
                : "Butuh approval manusia sebelum dieksekusi."}{" "}
              Params: <span className="mono">{params}</span>
            </div>
          </div>
        </div>
      </div>

      {plan.rationale ? <div className="goal-rationale">{plan.rationale}</div> : null}

      {shownWarnings.length ? (
        <ul className="goal-warnings">
          {shownWarnings.map((warning, index) => (
            <li key={`${index}-${warning}`}>
              <Icon name="i-alert-triangle" className="icon sm" />
              <span>{warning}</span>
            </li>
          ))}
        </ul>
      ) : null}

      <div className="goal-hashes">
        <div>
          <span className="k">plan hash</span>
          <code title={planHash}>{shortHash(planHash)}</code>
        </div>
        <div>
          <span className="k">evidence</span>
          <code title={plan.evidence_hash}>{shortHash(plan.evidence_hash)}</code>
        </div>
        {planHash ? <CopyButton text={planHash} label="Copy hash" /> : null}
      </div>
    </div>
  );
}
