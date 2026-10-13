interface UnavailableNoteProps {
  title: string;
  description: string;
}

/** Small placeholder for an optional section the engine does not provide yet. */
export function UnavailableNote({ title, description }: UnavailableNoteProps) {
  return (
    <section
      role="status"
      className="rounded-lg border border-dashed border-border bg-surface px-5 py-4"
    >
      <h2 className="text-sm font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-muted">{description}</p>
    </section>
  );
}
