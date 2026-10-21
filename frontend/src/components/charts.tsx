import type { HourBucket } from "../data/types";

const W = 760;
const H = 196;
const X0 = 36;
const X1 = 752;
const Y0 = 16;
const Y1 = 164;

export function ActivityChart({ buckets }: { buckets: HourBucket[] }) {
  const max = Math.max(1, ...buckets.map((bucket) => bucket.total));
  const step = (X1 - X0) / Math.max(1, buckets.length);
  const width = Math.max(3, step * 0.5);
  const grid = [0, 0.5, 1];

  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label="Healer decisions per hour">
      {grid.map((fraction) => {
        const y = Y1 - fraction * (Y1 - Y0);
        return (
          <g key={fraction}>
            <line className="grid-line" x1={X0} y1={y} x2={X1} y2={y} />
            <text className="axis-label" x={X0 - 8} y={y + 3} textAnchor="end">
              {Math.round(max * fraction)}
            </text>
          </g>
        );
      })}
      {buckets.map((bucket, index) => {
        const x = X0 + index * step + (step - width) / 2;
        const totalHeight = (bucket.total / max) * (Y1 - Y0);
        const escalatedHeight = (bucket.escalated / max) * (Y1 - Y0);
        const baseHeight = Math.max(0, totalHeight - escalatedHeight);
        return (
          <g key={bucket.label + index}>
            {bucket.total > 0 ? (
              <rect
                className="bar"
                x={x}
                y={Y1 - baseHeight}
                width={width}
                height={baseHeight}
                rx={1.5}
              />
            ) : null}
            {escalatedHeight > 0 ? (
              <rect
                className="bar escalated"
                x={x}
                y={Y1 - totalHeight}
                width={width}
                height={escalatedHeight}
                rx={1.5}
              />
            ) : null}
          </g>
        );
      })}
      {buckets.map((bucket, index) => {
        if (index % 6 !== 0 && index !== buckets.length - 1) return null;
        const x = X0 + index * step + step / 2;
        return (
          <text key={`label-${index}`} className="axis-label" x={x} y={186} textAnchor="middle">
            {bucket.label}
          </text>
        );
      })}
    </svg>
  );
}
