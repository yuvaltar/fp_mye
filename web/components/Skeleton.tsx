/** Placeholder block shown while data loads. */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={`animate-[pulse-soft_1.6s_ease-in-out_infinite] rounded-md bg-surface-raised ${className}`}
    />
  );
}
