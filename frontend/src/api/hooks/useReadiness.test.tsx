/* The readiness reading, through the generated client.
 *
 * `not ready` is an answer and not a failure: only a response the contract does not describe, or
 * a request that never arrives, becomes an error state. */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  notReadyResponse,
  pendingHandler,
  readyz,
  unreachableHandler,
} from "../../testing/apiStub";
import { renderAt, renderSignedInAt } from "../../testing/renderRoute";
import { UNEXPECTED_PROBLEM_TYPE, UNREACHABLE_PROBLEM_TYPE } from "../problem";

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
