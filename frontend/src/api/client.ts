/* The one HTTP client.
 *
 * `paths` is generated from the committed OpenAPI document, so a route or a field the api
 * does not serve is a compile error rather than a runtime surprise, and no response type is
 * ever hand-written.
 *
 * One instance, module-scoped. A second instance would be a second place for the credential
 * policy and the base URL to be decided.
 *
 * `baseUrl` is the document's own origin, because the browser always talks to one: in the
 * deployed stack Caddy serves this build and forwards the api paths, and in development Vite's
 * proxy does the same. It is the origin rather than an empty string so every request carries an
 * absolute URL, which `Request` requires outside a browser and which makes the target of a call
 * unambiguous in a log. `credentials: include` is what carries the session cookie on that one
 * origin, and it is set here rather than per call so a new hook cannot forget it.
 *
 * THE WEEKLY-SESSION HEADER IS SET HERE FOR THE SAME REASON. Only the caller knows whether the weekly session is
 * open, so every mutation made inside one has to say so, and there are six of them on the week screen with a seventh
 * arriving whenever a route is added. Deciding it per call site is how one of them comes to forget: this reads the
 * mode's own flag at the moment the request is built, on unsafe methods only, and sends nothing at all outside a
 * session. The api resolves the header only where a verdict is recorded, because its refusal for an unreadable value
 * says nothing was changed -- which is true of a mutation and meaningless on a read. */

import createClient from "openapi-fetch";

import { isSessionModeOpen, SESSION_MODE_HEADER, SESSION_MODE_OPEN } from "./sessionMode";
import type { paths } from "./schema";

/* Every method that can change something, read as a set rather than as a negation of the safe ones, so a method
 * nobody thought about carries no header rather than carrying one. */
const UNSAFE_METHODS: ReadonlySet<string> = new Set(["POST", "PATCH", "PUT", "DELETE"]);

export const client = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "include",
});

client.use({
  onRequest({ request }) {
    if (!isSessionModeOpen() || !UNSAFE_METHODS.has(request.method.toUpperCase())) return undefined;
    request.headers.set(SESSION_MODE_HEADER, SESSION_MODE_OPEN);
    return request;
  },
});
