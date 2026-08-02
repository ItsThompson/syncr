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
 * origin, and it is set here rather than per call so a new hook cannot forget it. */

import createClient from "openapi-fetch";

import type { paths } from "./schema";

export const client = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "include",
});
