"use client";

export interface RangeOption {
  label: string;
  /** Calendar days back from the latest point; null means all of it. */
  days: number | null;
}

interface RangeSelectorProps {
  label: string;
  options: readonly RangeOption[];
  value: number | null;
  onChange: (days: number | null) => void;
}

/** Small segmented control for picking how much history a chart shows. */
export function RangeSelector({ label, options, value, onChange }: RangeSelectorProps) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-surface-raised p-0.5">
      {options.map((option) => {
        const selected = option.days === value;
        return (
          <button
            key={option.label}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(option.days)}
            className={`rounded px-2.5 py-1 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent ${
              selected ? "bg-surface text-text shadow-sm" : "text-muted hover:text-text"
            }`}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
