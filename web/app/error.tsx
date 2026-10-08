"use client";

import { StateMessage, actionClassName } from "@/components/StateMessage";

export default function ErrorPage({ retry }: { error: Error; retry: () => void }) {
  return (
    <main>
      <StateMessage
        tone="error"
        title="Something went wrong"
        description="We could not load this page. The prediction API may be down or unreachable. Try again in a moment."
        action={
          <button type="button" onClick={() => retry()} className={actionClassName}>
            Try again
          </button>
        }
      />
    </main>
  );
}
