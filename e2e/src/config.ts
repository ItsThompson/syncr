/* Where the harness reaches the stack, and who it signs in as.
 *
 * The port is the one `e2e/docker-compose.e2e.yml` publishes and nothing else on a developer's
 * machine owns. The account is the one `just e2e-up` bootstraps, and its password is deliberately
 * not a secret: it exists only inside a scratch stack whose database has no published port.
 */

export const BASE_URL =
  process.env.SYNCR_E2E_BASE_URL ?? `http://localhost:${process.env.SYNCR_E2E_PORT ?? "57080"}`;

export const E2E_EMAIL = process.env.SYNCR_E2E_EMAIL ?? "e2e@syncr.test";
export const E2E_PASSWORD = process.env.SYNCR_E2E_PASSWORD ?? "e2e-password-not-a-secret";

/* The tenant's home zone. Every fixture declares this one, so a wall time in a fixture and a wall
 * time in an assertion mean the same instant. */
export const HOME_ZONE = "Europe/London";

/* The mocked provider, as the API reaches it: a service name on `app-net`, resolved by Docker's
 * DNS, fetched over a real socket. Not `localhost`: the fetch happens inside the api container. */
export const ICS_PROVIDER = "http://ics-provider";

/* How long a scenario waits for the worker to pick work up. The worker ticks every 5 seconds and
 * the debounce is 1.5 seconds, so three ticks is comfortably more than one of each without being
 * a wait a failing run has to sit through. */
export const WORKER_GRACE_MS = 20_000;
