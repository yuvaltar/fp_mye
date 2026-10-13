/** Marks generated example data so it is never mistaken for engine output. */
export function SampleDataBadge() {
  return (
    <span
      title="Generated example data. It will be replaced by real engine output once the engine provides this endpoint."
      className="inline-flex items-center rounded-full border border-up/40 bg-up/10 px-2 py-0.5 text-[0.7rem] font-medium uppercase tracking-wide text-up"
    >
      Sample data
    </span>
  );
}
