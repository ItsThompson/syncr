/* Vitest setup.
 *
 * The api interceptor errors on an UNHANDLED request, so a component that starts fetching
 * something no test declared fails loudly instead of reaching a real socket. */

import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterAll, afterEach } from "vitest";

import { apiServer } from "./apiServer";
import { installLayoutStubs } from "./layoutStubs";

/* Radix's Select and Popover measure and capture the pointer, and jsdom implements neither. Installed
 * here rather than per test file, because a control that throws on open would otherwise fail for a
 * reason unrelated to whatever the test was about. */
installLayoutStubs();

/* Started at module scope, NOT in `beforeAll`. The interceptor replaces `globalThis.fetch`, and
 * the api client captures that reference when its module is first imported: a `beforeAll` hook
 * runs after every import, so the client would keep the unpatched fetch and every request would
 * reach a real socket. A setup file is evaluated before the test module, which is early enough. */
apiServer.listen({ onUnhandledRequest: "error" });

afterEach(() => {
  cleanup();
  apiServer.resetHandlers();
});

afterAll(() => {
  apiServer.close();
});
