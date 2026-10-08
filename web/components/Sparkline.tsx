import { sparklinePath } from "@/lib/derive";

interface SparklineProps {
  values: readonly number[];
  label: string;
  width?: number;
  height?: number;
}

/** Tiny line chart with no axes, for table rows. */
export function Sparkline({ values, label, width = 96, height = 28 }: SparklineProps) {
  const path = sparklinePath(values, width, height);
  if (path === "") return null;
  return (
    <svg
      role="img"
      aria-label={label}
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className="shrink-0 overflow-visible"
    >
      <path d={path} fill="none" strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" className="stroke-accent" />
    </svg>
  );
}
