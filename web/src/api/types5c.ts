// The Stage 5C shapes (sign-in, the published view, the changelog, admin), derived from
// the generated `schema.d.ts` (`make client`); the drift check fails when they diverge.
// Only the role literal and the gap-of-a-field alias are written by hand.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Role = "reviewer" | "approver" | "admin" | "api_client";

export type Me = Schemas["MeOut"];

export type PublishedTender = Schemas["PublishedTender"];
export type PublishedSection = Schemas["PublishedSection"];
export type PublishedField = Schemas["PublishedField"];
export type PublishedEvidence = Schemas["Evidence"];
export type PublicationState = Schemas["PublicationState"]["state"];
export type Suspension = Schemas["Suspension"];

export type TenderChanges = Schemas["Changelog"];
export type ChangesVersion = Schemas["ChangelogVersion"];
export type Change = Schemas["Change"];

export type TenderListItem = Schemas["TenderOut"];

export type AdminUser = Schemas["UserOut"];
export type UserPatch = Schemas["UserPatch"];
export type ApiKeyInfo = Schemas["ApiKeyOut"];
export type ApiKeyCreate = Schemas["ApiKeyCreate"];
export type CreatedApiKey = Schemas["ApiKeyCreated"];
export type ReviewTokenOut = Schemas["ReviewTokenOut"];
export type Usage = Schemas["UsageOut"];
