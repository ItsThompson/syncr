/* The api interceptor, shared by every test file.
 *
 * One server, started once per test file and reset after each test, so a handler cannot leak into
 * the next test. `setup.ts` owns the lifecycle; a test only adds handlers.
 *
 * TWO DEFAULTS RATHER THAN SOMETHING EACH TEST INSTALLS, because every render goes through the gate and the gate
 * makes two reads of its own: the session, whose uninteresting case is a signed-in reader, and the Google
 * connection, whose uninteresting case is an account nobody has connected and nothing degraded. The second is there
 * because a banner outlives the screen that explains it, so the shell reads it on every screen.
 *
 * `resetHandlers` restores these defaults after each test, and a test that cares says so by overriding one. */

import { setupServer } from "msw/node";

import { googleConnection, session } from "./apiStub";

export const apiServer = setupServer(session(), googleConnection());
