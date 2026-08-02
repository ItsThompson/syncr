/* The api interceptor, shared by every test file.
 *
 * One server, started once per test file and reset after each test, so a handler cannot leak into
 * the next test. `setup.ts` owns the lifecycle; a test only adds handlers.
 *
 * The session handler is a DEFAULT rather than something each test installs: every render goes
 * through the gate, so the uninteresting case is a signed-in reader. `resetHandlers` restores this
 * default after each test, and a test that cares says so by overriding it. */

import { setupServer } from "msw/node";

import { session } from "./apiStub";

export const apiServer = setupServer(session());
