/* The api interceptor, shared by every test file.
 *
 * One server, started once per test file and reset after each test, so a handler cannot leak into
 * the next test. `setup.ts` owns the lifecycle; a test only adds handlers.
 *
 * FIVE DEFAULTS RATHER THAN SOMETHING EACH TEST INSTALLS, because every render goes through the gate and the gate
 * makes five requests of its own:
 *
 *   the session           uninteresting case: a signed-in reader
 *   the Google connection uninteresting case: an account nobody has connected and nothing degraded. It is here
 *                         because a banner outlives the screen that explains it, so the shell reads it on every
 *                         screen
 *   the push stream       uninteresting case: a connection that is open with nothing to say
 *   the Areas             the capture host reads them, because a capture needs an Area and `n` is global, so a
 *                         reader pressing it must not wait for a read the shell could already have made
 *   the settings          the same host reads the home zone, which is what a deadline and the date field are
 *                         read in
 *
 * The last two arrived with the capture host and were briefly absent, which produced 207 unhandled-request
 * errors across the suite: enough noise to hide the next real missing handler, which is what these defaults
 * exist to keep visible.
 *
 * `resetHandlers` restores these defaults after each test, and a test that cares says so by overriding one.
 */

import { setupServer } from "msw/node";

import { areas, events, googleConnection, session, settings } from "./apiStub";

export const apiServer = setupServer(session(), googleConnection(), events(), areas(), settings());
