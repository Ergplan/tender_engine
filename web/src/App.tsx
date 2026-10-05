import { MessagePage } from "./review/MessagePage";
import { ReviewApp } from "./review/ReviewApp";

const REVIEW = /^\/review\/([A-Za-z0-9_-]{16,64})(\/summary)?\/?$/;

/** There is no list page in phase 1: a reviewer arrives by their link. */
export function App({ path = window.location.pathname }: { path?: string }) {
  const match = REVIEW.exec(path);
  if (match) return <ReviewApp token={match[1]} summary={match[2] !== undefined} />;
  return (
    <MessagePage
      title="Tender Intelligence Engine"
      message="Open the review link you were sent. If you do not have one, ask for it."
    />
  );
}
