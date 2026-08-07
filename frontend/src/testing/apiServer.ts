/* The api interceptor, shared by every test file.
 *
 * One server, started once per test file and reset after each test, so a handler cannot leak into
 * the next test. `setup.ts` owns the lifecycle; a test only adds handlers.
 *
 * THREE DEFAULTS RATHER THAN SOMETHING EACH TEST INSTALLS, because every render goes through the gate and the gate
 * makes three requests of its own: the session, whose uninteresting case is a signed-in reader; the Google
 * connection, whose uninteresting case is an account nobody has connected and nothing degraded; and the push
 * stream, whose uninteresting case is a connection that is open with nothing to say. The second is there because a
 * banner outlives the screen that explains it, so the shell reads it on every screen, and the third because the
 * shell owns one connection for the whole application.
 *
 * `resetHandlers` restores these defaults after each test, and a test that cares says so by overriding one.
 */

import { setupServer } from "msw/node";

import { events, googleConnection, session } from "./apiStub";

export const apiServer = setupServer(session(), googleConnection(), events());
