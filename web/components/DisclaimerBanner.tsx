import Link from "next/link";

export function DisclaimerBanner() {
  return (
    <div
      role="note"
      className="border-b border-border bg-surface px-4 py-1.5 text-center text-xs text-muted"
    >
      Educational project — not investment advice.{" "}
      <Link href="/disclaimer" className="underline underline-offset-2 hover:text-text">
        Disclaimer
      </Link>
    </div>
  );
}
