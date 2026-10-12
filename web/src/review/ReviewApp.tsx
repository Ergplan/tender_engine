import { Component, type ReactNode, useEffect, useMemo, useState } from "react";

import { ApiError, reviewApi, type ReviewSession, type TenderReview } from "../api/client";
import { AmendmentsPage } from "./AmendmentsPage";
import { MessagePage } from "./MessagePage";
import { ReviewScreen } from "./ReviewScreen";
import { SummaryPage } from "./SummaryPage";

type State =
  | { kind: "loading" }
  | { kind: "ready"; session: ReviewSession; review: TenderReview }
  | { kind: "refused"; message: string };

export type ReviewPage = "review" | "summary" | "amendments";

/** A fault in the screen leaves a plain message, not an empty page. Decisions are saved
 * as they are made, so nothing is lost by reloading. */
class Safely extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <MessagePage
          title="Something went wrong on this page"
          message="Reload the page to continue. Every decision you made is already saved."
        />
      );
    return this.props.children;
  }
}

/** /review/<token> opens straight into the tender; /review/<token>/amendments shows what
 * each later version changed; /review/<token>/summary is the read-only view after
 * completion. */
export function ReviewApp({ token, page }: { token: string; page: ReviewPage }) {
  const api = useMemo(() => reviewApi(token), [token]);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [shown, setShown] = useState<ReviewPage>(page);

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
  if (shown === "summary")
    return <SummaryPage api={api} tenderId={state.session.tender_id} reviewHref={base} />;
  if (shown === "amendments")
    return (
      <Safely>
        <AmendmentsPage api={api} session={state.session} review={state.review} reviewHref={base} />
      </Safely>
    );
  return (
    <Safely>
      <ReviewScreen
        api={api}
        session={state.session}
        initial={state.review}
        amendmentsHref={`${base}/amendments`}
        onCompleted={() => {
          window.history.pushState(null, "", `${base}/summary`);
          setShown("summary");
        }}
      />
    </Safely>
  );
}
