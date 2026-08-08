/* One HTTP client for the whole harness, over the ONE origin the browser uses.
 *
 * Every request goes through Caddy to `api:8000`, exactly as the browser's do, so the session
 * cookie's `SameSite=Lax` and the origin check on every unsafe method are both exercised by the
 * seeder and by every API-level scenario rather than bypassed by a second published port.
 *
 * Node's fetch keeps no cookie jar, so the session identifier is carried explicitly. That is not a
 * workaround: it makes the credential visible at the one place it is set, and it is the same value
 * the browser context is later seeded with.
 */

import {
  IDEMPOTENCY_KEY_HEADER,
  ORIGIN_HEADER,
  SESSION_COOKIE,
  SESSION_MODE_HEADER,
} from "./headers.ts";

export type FieldError = {
  readonly field?: string;
  readonly message?: string;
};

export type Problem = {
  readonly type?: string;
  readonly title?: string;
  readonly detail?: string;
  readonly status?: number;
  readonly errors?: readonly FieldError[] | null;
};

export type Reply<T> = {
  readonly status: number;
  readonly body: T;
  readonly headers: Headers;
};

export type RequestOptions = {
  /** Sent as `Idempotency-Key`. A mutation replayed under one key must not duplicate. */
  readonly idempotencyKey?: string;
  /** Sent as `X-Syncr-Session-Mode`, which is what attributes a verdict transition to a session. */
  readonly sessionMode?: boolean;
};

export type ApiClient = {
  readonly baseUrl: string;
  /** The session identifier, for seeding a browser context with the same credential. */
  readonly sessionCookie: string;
  /** Reads and writes that must succeed. A non-2xx throws with the problem document in the message. */
  get: <T>(path: string) => Promise<T>;
  post: <T>(path: string, body?: unknown, options?: RequestOptions) => Promise<T>;
  put: <T>(path: string, body?: unknown, options?: RequestOptions) => Promise<T>;
  patch: <T>(path: string, body?: unknown, options?: RequestOptions) => Promise<T>;
  del: <T>(path: string, options?: RequestOptions) => Promise<T>;
  /** The status and the body, for a case whose subject IS the refusal. */
  attempt: <T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions,
  ) => Promise<Reply<T>>;
};

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

const readBody = async (response: Response): Promise<unknown> => {
  const text = await response.text();
  if (text.length === 0) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
};

/* A 422 states "1 request field(s) failed validation" in its detail and names the field in `errors`,
 * so the field list is appended rather than left for a reader to go looking for. */
const stated = (method: string, path: string, reply: Reply<unknown>): string => {
  const problem = reply.body as Problem | null;
  const detail = problem?.detail ?? JSON.stringify(reply.body);
  const fields = problem?.errors?.length ? ` ${JSON.stringify(problem.errors)}` : "";
  return `${method} ${path} answered ${reply.status}: ${problem?.type ?? "no type"} ${detail}${fields}`;
};

/** A client whose requests carry `credential`, which every method below sends. */
export const clientFor = (baseUrl: string, sessionCookie: string): ApiClient => {
  const attempt = async <T>(
    method: string,
    path: string,
    body?: unknown,
    options: RequestOptions = {},
  ): Promise<Reply<T>> => {
    const headers = new Headers({ Cookie: `${SESSION_COOKIE}=${sessionCookie}` });
    if (UNSAFE_METHODS.has(method)) headers.set(ORIGIN_HEADER, baseUrl);
    if (body !== undefined) headers.set("Content-Type", "application/json");
    if (options.idempotencyKey) headers.set(IDEMPOTENCY_KEY_HEADER, options.idempotencyKey);
    if (options.sessionMode) headers.set(SESSION_MODE_HEADER, "true");

    const response = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    return {
      status: response.status,
      body: (await readBody(response)) as T,
      headers: response.headers,
    };
  };

  const demand = async <T>(
    method: string,
    path: string,
    body?: unknown,
    options?: RequestOptions,
  ): Promise<T> => {
    const reply = await attempt<T>(method, path, body, options);
    if (reply.status >= 400) throw new Error(stated(method, path, reply));
    return reply.body;
  };

  return {
    baseUrl,
    sessionCookie,
    get: (path) => demand("GET", path),
    post: (path, body, options) => demand("POST", path, body, options),
    put: (path, body, options) => demand("PUT", path, body, options),
    patch: (path, body, options) => demand("PATCH", path, body, options),
    del: (path, options) => demand("DELETE", path, undefined, options),
    attempt,
  };
};

/** Sign in through the real route and keep the cookie it set. */
export const signIn = async (
  baseUrl: string,
  email: string,
  password: string,
): Promise<ApiClient> => {
  const response = await fetch(`${baseUrl}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json", [ORIGIN_HEADER]: baseUrl },
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw new Error(
      `sign-in as ${email} answered ${response.status}: ${await response.text()}. ` +
        "Has `just e2e-up` run, and did it bootstrap this account?",
    );
  }
  const cookie = response.headers
    .getSetCookie()
    .find((set) => set.startsWith(`${SESSION_COOKIE}=`));
  if (!cookie) throw new Error(`sign-in set no ${SESSION_COOKIE} cookie`);
  const value = cookie.slice(`${SESSION_COOKIE}=`.length).split(";")[0];
  if (!value) throw new Error(`the ${SESSION_COOKIE} cookie carried no value`);
  return clientFor(baseUrl, value);
};
