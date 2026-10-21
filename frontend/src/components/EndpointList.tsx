import type { SourceStatus } from "../data/types";
import { Icon } from "./Icon";
import { Empty, Pill } from "./ui";

export function EndpointList({ endpoints }: { endpoints: SourceStatus[] }) {
  if (!endpoints.length) return <Empty>Belum ada endpoint yang diprobe.</Empty>;
  return (
    <>
      {endpoints.map((endpoint) => (
        <div className="check" key={endpoint.name}>
          <span className={`check-ico ${endpoint.ok ? "tone-mint" : "tone-coral"}`}>
            <Icon name={endpoint.ok ? "i-check" : "i-x"} />
          </span>
          <div className="check-main">
            <div className="check-name">
              {endpoint.name}
              {endpoint.detail ? <span className="hint"> · {endpoint.detail}</span> : null}
            </div>
            <div className="check-val">{endpoint.url.split("?")[0]}</div>
          </div>
          <Pill tone={endpoint.ok ? "mint" : "coral"}>{endpoint.ok ? `${endpoint.ms} ms` : "fail"}</Pill>
        </div>
      ))}
    </>
  );
}
