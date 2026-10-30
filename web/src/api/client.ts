// The only place fetch() appears. Types come from schema.d.ts, which is generated from the
// API's OpenAPI document by `make client`; the watcher fails when it drifts.
import type { components } from "./schema";
import type * as T5 from "./types5c";

type Schemas = components["schemas"];
export type Health = Schemas["HealthResponse"];
export type ReviewSession = Schemas["ReviewSessionOut"];
export type TenderReview = Schemas["TenderReview"];
export type ReviewField = Schemas["ReviewField"];
export type ReviewEntry = Schemas["ReviewEntry"];
export type ReviewVersion = Schemas["ReviewVersion"];
export type ReviewDocument = Schemas["ReviewDocument"];
export type FieldState = Schemas["FieldState"];
export type Candidate = Schemas["CandidateView"];
export type Evidence = Schemas["EvidenceView"];
export type Approval = Schemas["ApprovalView"];
export type DocumentInfo = Schemas["DocumentOut"];
export type PageInfo = Schemas["PageOut"];
export type SectionInfo = Schemas["SectionOut"];
export type SearchHit = Schemas["SearchHit"];
export type Snapshot = Schemas["SnapshotOut"];
export type TenderAmendments = Schemas["TenderAmendments"];
export type AmendmentVersion = Schemas["AmendmentVersion"];
export type AmendmentChange = Schemas["AmendmentChange"];
export type ApprovalRequest = Schemas["ApprovalRequest"];
export type ApprovalResult = Schemas["ApprovalOut"];
export type AwardReview = Schemas["AwardReview"];
export type AwardInfo = Schemas["AwardOut"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly errorType: string,
    message: string,
    readonly detail: string | null,
    readonly requestId: string | null,
  ) {
    super(message);
  }
}

async function request<T>(
  method: string,
  path: string,
  token?: string,
  body?: unknown,
  extraHeaders: Record<string, string> = {},
): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", ...extraHeaders };
  if (token) headers["X-Review-Token"] = token;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error_type?: string;
      message?: string;
      detail?: string | null;
      request_id?: string;
    } | null;
    throw new ApiError(
      response.status,
      payload?.error_type ?? "unknown",
      payload?.message ?? `Request failed with status ${response.status}`,
      payload?.detail ?? null,
      payload?.request_id ?? response.headers.get("X-Request-Id"),
    );
  }
  return (await response.json()) as T;
}

export type Reliability = Schemas["ReliabilityOut"];

export const api = {
  health: () => request<Health>("GET", "/health"),
  /** The reliability dashboard's data; the admin token goes in a header, never in the URL. */
  reliability: (adminToken: string) =>
    request<Reliability>("GET", "/admin/reliability", undefined, undefined, { "X-Admin-Token": adminToken }),
};

/** The calls of one review link. Every one carries the token. */
export function reviewApi(token: string) {
  const get = <T>(path: string) => request<T>("GET", path, token);
  return {
    session: () => get<ReviewSession>("/review-session"),
    review: (tenderId: string) => get<TenderReview>(`/tenders/${tenderId}/review`),
    decide: (body: ApprovalRequest) => request<ApprovalResult>("POST", "/approvals", token, body),
    complete: (tenderId: string) =>
      request<Snapshot>("POST", `/tenders/${tenderId}/complete-review`, token),
    snapshot: (tenderId: string) => get<Snapshot>(`/tenders/${tenderId}/snapshot`),
    /** An award (Stage 6): the publication's review and its completion. */
    award: (awardId: string) => get<AwardReview>(`/awards/${awardId}/review`),
    completeAward: (awardId: string) =>
      request<AwardInfo>("POST", `/awards/${awardId}/complete-review`, token),
    amendments: (tenderId: string) => get<TenderAmendments>(`/tenders/${tenderId}/amendments`),
    document: (documentId: string) => get<DocumentInfo>(`/documents/${documentId}`),
    pages: (documentId: string) => get<PageInfo[]>(`/documents/${documentId}/pages`),
    sections: (documentId: string) => get<SectionInfo[]>(`/documents/${documentId}/sections`),
    search: (documentId: string, query: string) =>
      get<SearchHit[]>(`/documents/${documentId}/search?q=${encodeURIComponent(query)}`),
  };
}

export type ReviewApi = ReturnType<typeof reviewApi>;

/** The calls of a signed-in user (Stage 5C). The session travels as a cookie the browser
 * sends by itself on this origin; nothing is added to the request. */
export const appApi = {
  me: () => request<T5.Me>("GET", "/auth/me"),
  logout: () => request<unknown>("POST", "/auth/logout"),
  tenders: () => request<T5.TenderListItem[]>("GET", "/tenders"),
  published: (tenderId: string) => request<T5.PublishedTender>("GET", `/tenders/${tenderId}/published`),
  changes: (tenderId: string) => request<T5.TenderChanges>("GET", `/tenders/${tenderId}/changes`),
  users: () => request<T5.AdminUser[]>("GET", "/admin/users"),
  updateUser: (id: string, body: T5.UserPatch) =>
    request<T5.AdminUser>("PATCH", `/admin/users/${id}`, undefined, body),
  apiKeys: () => request<T5.ApiKeyInfo[]>("GET", "/admin/api-keys"),
  createApiKey: (body: T5.ApiKeyCreate) =>
    request<T5.CreatedApiKey>("POST", "/admin/api-keys", undefined, body),
  revokeApiKey: (id: string) => request<unknown>("DELETE", `/admin/api-keys/${id}`),
  createReviewToken: (body: { tender: string; reviewer_name: string }) =>
    request<T5.ReviewTokenOut>("POST", "/admin/review-tokens", undefined, body),
  usage: (days = 30) => request<T5.Usage>("GET", `/admin/usage?days=${days}`),
};

export type TenderSummary = Schemas["TenderOut"];
export type TenderStatus = Schemas["TenderStatus"];
export type VersionStatus = Schemas["VersionStatus"];
export type FieldsSnapshot = Schemas["TenderSnapshot"];
export type SnapshotField = Schemas["SnapshotField"];
export type SnapshotEvidence = Schemas["SnapshotEvidence"];
export type Submitted = Schemas["SubmitOut"];
export type AskAnswer = Schemas["AskAnswer"];
export type AskCitation = Schemas["Citation"];
export type ReviewLink = Schemas["ReviewLinkOut"];

async function send<T>(method: string, path: string, key: string, body?: BodyInit, contentType?: string): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json", Authorization: `Bearer ${key}` };
  if (contentType) headers["Content-Type"] = contentType;
  const response = await fetch(`/api/v1${path}`, { method, headers, body });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as {
      error_type?: string;
      message?: string;
      detail?: string | null;
      request_id?: string;
    } | null;
    throw new ApiError(
      response.status,
      payload?.error_type ?? "unknown",
      payload?.message ?? `Request failed with status ${response.status}`,
      payload?.detail ?? null,
      payload?.request_id ?? response.headers.get("X-Request-Id"),
    );
  }
  return (await response.json()) as T;
}

/** What a dropped tender carries besides its file. Empty values are left out. */
export type SubmitForm = {
  file?: File;
  sourceUrl?: string;
  tenderType?: string;
  agency?: string;
  title?: string;
  priority?: boolean;
};

function submitBody(form: SubmitForm, extra: Record<string, string> = {}): FormData {
  const data = new FormData();
  if (form.file) data.append("file", form.file, form.file.name);
  if (form.sourceUrl) data.append("source_url", form.sourceUrl);
  if (form.tenderType) data.append("tender_type", form.tenderType);
  if (form.agency) data.append("agency", form.agency);
  if (form.title) data.append("title", form.title);
  if (form.priority) data.append("priority", "true");
  for (const [name, value] of Object.entries(extra)) if (value) data.append(name, value);
  return data;
}

/** The workspace's calls (2026-10-30): an API key, kept in this browser, on every call. */
export function workspaceApi(key: string) {
  const json = <T>(method: string, path: string, body: unknown) =>
    send<T>(method, path, key, JSON.stringify(body), "application/json");
  return {
    tenders: () => send<TenderSummary[]>("GET", "/tenders", key),
    status: (tenderId: string) => send<TenderStatus>("GET", `/tenders/${tenderId}/status`, key),
    fields: (tenderId: string) => send<FieldsSnapshot>("GET", `/tenders/${tenderId}/fields`, key),
    amendments: (tenderId: string) => send<TenderAmendments>("GET", `/tenders/${tenderId}/amendments`, key),
    submit: (form: SubmitForm) => send<Submitted>("POST", "/tenders/submit", key, submitBody(form)),
    submitAmendment: (tenderId: string, form: SubmitForm & { kind: string; issuedOn?: string; summary?: string }) =>
      send<Submitted>(
        "POST",
        `/tenders/${tenderId}/submit-amendment`,
        key,
        submitBody(form, { kind: form.kind, issued_on: form.issuedOn ?? "", summary_of_change: form.summary ?? "" }),
      ),
    ask: (tenderId: string, question: string) => json<AskAnswer>("POST", `/tenders/${tenderId}/ask`, { question }),
    reviewLink: (tenderId: string, reviewerName: string) =>
      json<ReviewLink>("POST", `/tenders/${tenderId}/review-link`, { reviewer_name: reviewerName }),
    /** A page image as an object URL (an <img> cannot send the key itself). */
    pageImage: async (documentId: string, pageNo: number): Promise<string> => {
      const response = await fetch(`/api/v1/documents/${documentId}/pages/${pageNo}/render`, {
        headers: { Authorization: `Bearer ${key}` },
      });
      if (!response.ok) throw new ApiError(response.status, "page_unavailable", "The page image is not available yet.", null, null);
      return URL.createObjectURL(await response.blob());
    },
  };
}

export type WorkspaceApi = ReturnType<typeof workspaceApi>;
