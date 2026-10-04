// The only place fetch() appears. Types come from schema.d.ts, which is generated from the
// API's OpenAPI document by `make client`; the watcher fails when it drifts.
import type { components } from "./schema";

export type Health = components["schemas"]["HealthResponse"];

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly errorType: string,
    message: string,
    readonly requestId: string | null,
  ) {
    super(message);
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api/v1${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as {
      error_type?: string;
      message?: string;
      request_id?: string;
    } | null;
    throw new ApiError(
      response.status,
      body?.error_type ?? "unknown",
      body?.message ?? `Request failed with status ${response.status}`,
      body?.request_id ?? response.headers.get("X-Request-Id"),
    );
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => get<Health>("/health"),
};
