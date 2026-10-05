import { useEffect, useMemo, useState } from "react";

import { ApiError, reviewApi, type ReviewSession, type TenderReview } from "../api/client";
import { MessagePage } from "./MessagePage";
import { ReviewScreen } from "./ReviewScreen";
import { SummaryPage } from "./SummaryPage";

type State =
  | { kind: "loading" }
  | { kind: "ready"; session: ReviewSession; review: TenderReview }
  | { kind: "refused"; message: string };

/** /review/<token> opens straight into the tender; /review/<token>/summary is the
 * read-only view after completion. */
export function ReviewApp({ token, summary }: { token: string; summary: boolean }) {
  const api = useMemo(() => reviewApi(token), [token]);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [showSummary, setShowSummary] = useState(summary);

  useEffect(() => {
    let cancelled = false;
    // Page images and the PDF are fetched by the browser itself: the token travels as a cookie.
    document.cookie = `review_token=${encodeURIComponent(token)}; path=/; SameSite=Strict${
      window.location.protocol === "https:" ? "; Secure" : ""
    }`;
    (async () => {
      const session = await api.session();
      const review = await api.review(session.tender_id);
      if (!cancelled) setState({ kind: "ready", session, review });
    })().catch((error: unknown) => {
      if (cancelled) return;
      setState({
        kind: "refused",
        message: error instanceof ApiError ? error.message : "The review could not be opened. Check your connection and reload.",
      });
    });
    return () => {
      cancelled = true;
    };
  }, [api, token]);

  if (state.kind === "loading") return <p className="p-8 font-sans text-slate-600">Opening the review…</p>;
  if (state.kind === "refused") return <MessagePage title="This review cannot be opened" message={state.message} />;
  const base = `/review/${token}`;
  if (showSummary)
    return <SummaryPage api={api} tenderId={state.session.tender_id} reviewHref={base} />;
  return (
    <ReviewScreen
      api={api}
      session={state.session}
      initial={state.review}
      onCompleted={() => {
        window.history.pushState(null, "", `${base}/summary`);
        setShowSummary(true);
      }}
    />
  );
}
