/* The readiness reading, through the generated client.
 *
 * `not ready` is an answer and not a failure: only a response the contract does not describe, or
 * a request that never arrives, becomes an error state. */

import { renderHook, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  notReadyChecks,
  notReadyResponse,
  pendingHandler,
  readyz,
  unreachableHandler,
} from "../../testing/apiStub";
import { FreshCache, renderAt, renderSignedInAt } from "../../testing/renderRoute";
import { UNEXPECTED_PROBLEM_TYPE, UNREACHABLE_PROBLEM_TYPE } from "../../contract";
import { unreadyChecks, useReadiness } from "./useReadiness";

/* The row is in the DOM from the first paint, so an assertion has to wait for the VALUE to settle
 * rather than for the element to appear. */
const reading = (): string => screen.getByRole("definition").textContent ?? "";

describe("useReadiness", () => {
  it("reads a ready api as ready", async () => {
    apiServer.use(readyz());
    renderAt("/settings");

    await waitFor(() => expect(reading()).toBe("ready"));
  });

  it("reads a 503 as not ready rather than as an error", async () => {
    apiServer.use(readyz(notReadyResponse));
    renderAt("/settings");

    await waitFor(() => expect(reading()).toBe("not ready"));
  });

  /* The 503 body declares the same model as the 200, which is what lets the reading come from the
   * contract rather than from a status code the frontend hard-codes.
   *
   * Asserted through the HOOK's own output. An earlier version called `unreadyChecks` with the
   * fixture directly, so returning `checks: {}` from the hook kept every test green: the assertion
   * exercised the helper and not the thing the payload was made reachable for. */
  it("carries the checks payload, which names WHICH capability is unavailable", async () => {
    apiServer.use(readyz(notReadyResponse));

    const { result } = renderHook(() => useReadiness(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") throw new Error("the reading never settled");
    expect(result.current.data.checks).toEqual(notReadyChecks);
    expect(unreadyChecks(result.current.data)).toEqual(["migrations"]);
  });

  it("carries a passing check through on the ready path too", async () => {
    apiServer.use(readyz());

    const { result } = renderHook(() => useReadiness(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") throw new Error("the reading never settled");
    expect(Object.keys(result.current.data.checks)).toEqual(["postgres"]);
    expect(unreadyChecks(result.current.data)).toEqual([]);
  });

  it("does not read a fault as a healthy answer, even though Problem also carries a status", async () => {
    apiServer.use(
      readyz({
        status: 500,
        body: {
          type: "syncr:internal-error",
          title: "Internal server error",
          status: 500,
          detail: "The readiness aggregate could not be computed.",
        },
      }),
    );
    renderAt("/settings");

    await waitFor(() => expect(reading()).toBe("The readiness aggregate could not be computed."));
  });

  /* These two reach the literal-value narrowing, and nothing else did: the `typeof === "string"`
   * check above it already rejects Problem's NUMERIC status, so the fault case passes on the type
   * check alone and the narrowing could be deleted with all nine tests still green. A status string
   * the contract does not declare is the only input that tells the two lines apart. */
  it("refuses a status string the contract does not declare, rather than guessing", async () => {
    apiServer.use(readyz({ status: 200, body: { status: "degraded", checks: {} } }));
    renderAt("/settings");

    await waitFor(() => expect(reading()).toMatch(/answered 200 without a problem document/));
  });

  it("refuses a body carrying a declared status but no checks", async () => {
    apiServer.use(readyz({ status: 200, body: { status: "ready" } }));
    renderAt("/settings");

    await waitFor(() => expect(reading()).toMatch(/without a problem document/));
  });

  it("renders the api's own problem detail when the contract describes the failure", async () => {
    apiServer.use(
      readyz({
        status: 500,
        body: {
          type: "syncr:internal-error",
          title: "Internal server error",
          status: 500,
          detail: "The request could not be completed. Nothing was changed.",
        },
      }),
    );
    renderAt("/settings");

    await waitFor(() =>
      expect(reading()).toBe("The request could not be completed. Nothing was changed."),
    );
  });

  it("names what still works when the response is not a problem document", async () => {
    apiServer.use(readyz({ status: 502, body: "<html>bad gateway</html>" }));
    renderAt("/settings");

    await waitFor(() => expect(reading()).toMatch(/answered 502 without a problem document/));
    expect(UNEXPECTED_PROBLEM_TYPE).toBe("syncr:unexpected-response");
  });

  it("reports an unreachable api as a problem rather than as a pending read", async () => {
    apiServer.use(unreachableHandler("/readyz"));
    renderAt("/settings");

    await waitFor(() => expect(reading()).toMatch(/The request did not complete/));
    expect(UNREACHABLE_PROBLEM_TYPE).toBe("syncr:api-unreachable");
  });

  it("shows a static word while the read is in flight, never a spinner", async () => {
    apiServer.use(pendingHandler("/readyz"));
    await renderSignedInAt("/settings");

    expect(screen.getByRole("definition")).toHaveTextContent("reading");
  });

  it("labels the reading, so the label and the value cannot disagree", async () => {
    apiServer.use(readyz());
    renderAt("/settings");

    await waitFor(() => expect(reading()).toBe("ready"));
    expect(screen.getByRole("term")).toHaveTextContent("api");
  });
});
