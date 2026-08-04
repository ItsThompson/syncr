/* The week pattern's read and its replacement.
 *
 * The read's whole subtlety is the 404: the api answers one until a pattern is declared, and reading that as a
 * failure would put a first-run reader in front of an error surface saying something is broken. Every other
 * non-2xx is still a failure, which is the line these tests hold. */

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  countedHandler,
  jsonHandler,
  recordingHandler,
  unreachableHandler,
} from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import { buildWeekPattern } from "../../routes/templates/__tests__/fixtures";
import { useWeekPattern, useWeekPatternDeclaration } from "./useWeekPattern";

const PATH = "/api/v1/week-pattern";

describe("useWeekPattern", () => {
  it("reads a declared pattern", async () => {
    apiServer.use(jsonHandler(PATH, { status: 200, body: buildWeekPattern() }));

    const { result } = renderHook(() => useWeekPattern(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") throw new Error("the reading never settled");
    expect(result.current.data).toEqual(buildWeekPattern());
  });

  /* A 404 is the api's answer before a pattern exists, and this route takes no path parameter, so it can mean
   * nothing else. */
  it("reads a 404 as `not declared yet` rather than as a failure", async () => {
    apiServer.use(
      jsonHandler(PATH, {
        status: 404,
        body: {
          type: "syncr:not-found",
          title: "Not found",
          status: 404,
          detail: "No week pattern is declared. Declare one before solving a week.",
        },
      }),
    );

    const { result } = renderHook(() => useWeekPattern(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") throw new Error("the reading never settled");
    expect(result.current.data).toBeNull();
  });

  it("reads a 500 as a failure, with the api's own sentence", async () => {
    apiServer.use(
      jsonHandler(PATH, {
        status: 500,
        body: {
          type: "syncr:internal-error",
          title: "Internal server error",
          status: 500,
          detail: "One weekday of the pattern could not be read.",
        },
      }),
    );

    const { result } = renderHook(() => useWeekPattern(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("error"));
    if (result.current.status !== "error") throw new Error("the reading never failed");
    expect(result.current.problem.detail).toContain("One weekday of the pattern");
  });

  it("reads an unreachable api as a failure rather than as no pattern", async () => {
    apiServer.use(unreachableHandler(PATH));

    const { result } = renderHook(() => useWeekPattern(), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("error"));
  });
});

describe("useWeekPatternDeclaration", () => {
  it("sends the whole mapping to the pattern route", async () => {
    const write = recordingHandler("put", PATH, { status: 200, body: buildWeekPattern() });
    apiServer.use(write.handler, jsonHandler(PATH, { status: 200, body: buildWeekPattern() }));

    const { result } = renderHook(() => useWeekPatternDeclaration(), { wrapper: FreshCache });
    await expect(result.current.submit(buildWeekPattern())).resolves.toBe(true);

    expect(write.bodies).toEqual([buildWeekPattern()]);
  });

  it("invalidates the pattern it replaced, so the table redraws once", async () => {
    const read = countedHandler(PATH, { status: 200, body: buildWeekPattern() });
    apiServer.use(read.handler, recordingHandler("put", PATH, { status: 200, body: null }).handler);

    const { result } = renderHook(
      () => ({ reading: useWeekPattern(), write: useWeekPatternDeclaration() }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.reading.status).toBe("ready"));
    expect(read.count()).toBe(1);

    await result.current.write.submit(buildWeekPattern());

    await waitFor(() => expect(read.count()).toBe(2));
  });

  it("keeps a refusal, with the member the api named, and reports that nothing was applied", async () => {
    apiServer.use(
      recordingHandler("put", PATH, {
        status: 422,
        body: {
          type: "syncr:validation-failed",
          title: "Validation failed",
          status: 422,
          detail: "Every weekday names a day type. Nothing was changed.",
          errors: [{ field: "sunday", message: "field required" }],
        },
      }).handler,
    );

    const { result } = renderHook(() => useWeekPatternDeclaration(), { wrapper: FreshCache });
    await expect(result.current.submit(buildWeekPattern())).resolves.toBe(false);

    await waitFor(() => expect(result.current.problem).not.toBeNull());
    expect(result.current.problem?.errors).toEqual([
      { field: "sunday", message: "field required" },
    ]);
  });

  it("reports an unreachable api as a refusal rather than throwing out of the handler", async () => {
    apiServer.use(unreachableHandler(PATH, "put"));

    const { result } = renderHook(() => useWeekPatternDeclaration(), { wrapper: FreshCache });
    await expect(result.current.submit(buildWeekPattern())).resolves.toBe(false);

    await waitFor(() => expect(result.current.problem?.status).toBe(0));
  });
});
