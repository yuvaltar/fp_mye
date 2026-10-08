import { Skeleton } from "@/components/Skeleton";

export default function Loading() {
  return (
    <main aria-busy="true" aria-label="Loading watchlist">
      <Skeleton className="h-8 w-40" />
      <Skeleton className="mt-3 mb-6 h-4 w-96 max-w-full" />
      <div className="space-y-px overflow-hidden rounded-lg border border-border bg-surface">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 rounded-none" />
        ))}
      </div>
    </main>
  );
}
