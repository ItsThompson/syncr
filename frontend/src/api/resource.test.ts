/* The one shape a hook returns, and the three states it can be in. */

import type { SWRResponse } from "swr";
import { describe, expect, it } from "vitest";

import type { Problem } from "./problem";
import { toResource } from "./resource";

const problem: Problem = {
  type: "syncr:not-found",
  title: "Not found",
  status: 404,
  detail: "No such week.",
};

/* SWR's response carries a mutate function and revalidation flags this adapter never reads;
 * building the full type keeps the test honest about which fields the adapter depends on. */
function swrResponse<T>(fields: Partial<SWRResponse<T, Problem>>): SWRResponse<T, Problem> {
  return {
    data: undefined,
    error: undefined,
    isLoading: false,
    isValidating: false,
    mutate: (() => Promise.resolve(undefined)) as SWRResponse<T, Problem>["mutate"],
    ...fields,
  };
}

describe("toResource", () => {
  it("is loading until data arrives", () => {
    expect(toResource(swrResponse<number>({}))).toEqual({ status: "loading" });
  });

  it("is ready once data arrives", () => {
    expect(toResource(swrResponse({ data: 7 }))).toEqual({ status: "ready", data: 7 });
  });

  it("is ready for a falsy value, which is data and not absence", () => {
    expect(toResource(swrResponse({ data: 0 }))).toEqual({ status: "ready", data: 0 });
  });

  it("carries the problem on an error", () => {
    expect(toResource(swrResponse<number>({ error: problem }))).toEqual({
      status: "error",
      problem,
    });
  });

  it("lets an error win over stale data, so a component cannot render both", () => {
    expect(toResource(swrResponse({ data: 7, error: problem }))).toEqual({
      status: "error",
      problem,
    });
  });
});
