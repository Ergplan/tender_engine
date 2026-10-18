import { AdminPage } from "./admin/AdminPage";
import { ReliabilityPage } from "./admin/ReliabilityPage";
import { Shell } from "./app/Shell";
import { LibraryPage } from "./library/LibraryPage";
import { PublishedPage } from "./library/PublishedPage";
import { ReviewApp } from "./review/ReviewApp";

const REVIEW = /^\/review\/([A-Za-z0-9_-]{16,64})(\/summary|\/amendments)?\/?$/;
const TENDER = /^\/tenders\/([0-9a-f]{32})(\/changes)?\/?$/;

/** Reviewers arrive by their link and never sign in; everyone else signs in and lands in
 * the library. The reliability dashboard keeps its admin token (Stage 4). */
export function App({
  path = window.location.pathname,
  search = window.location.search,
}: {
  path?: string;
  search?: string;
}) {
  const review = REVIEW.exec(path);
  if (review)
    return (
      <ReviewApp
        token={review[1]}
        page={review[2] === "/summary" ? "summary" : review[2] === "/amendments" ? "amendments" : "review"}
      />
    );
  if (/^\/admin\/reliability\/?$/.test(path)) return <ReliabilityPage />;
  const full = `${path}${search}`;
  const tender = TENDER.exec(path);
  let page = <LibraryPage filter={new URLSearchParams(search).get("filter") ?? ""} />;
  if (tender) page = <PublishedPage tenderId={tender[1]} tab={tender[2] ? "changes" : "facts"} />;
  else if (/^\/admin\/?$/.test(path)) page = <AdminPage />;
  return <Shell path={full}>{page}</Shell>;
}
