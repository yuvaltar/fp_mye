import Link from "next/link";
import { StateMessage, actionClassName } from "@/components/StateMessage";

export default function NotFound() {
  return (
    <main>
      <StateMessage
        title="Ticker not found"
        description="We have no data for that ticker. Pick one from the watchlist."
        action={
          <Link href="/" className={actionClassName}>
            Back to the watchlist
          </Link>
        }
      />
    </main>
  );
}
