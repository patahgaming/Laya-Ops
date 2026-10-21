import type { CSSProperties } from "react";

export function Icon({
  name,
  className = "icon",
  style
}: {
  name: string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg className={className} style={style} aria-hidden="true" focusable="false">
      <use href={`#${name}`} />
    </svg>
  );
}
