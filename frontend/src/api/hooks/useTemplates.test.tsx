/* Reading one day shape, and declaring an entry on it.
 *
 * TWO CLAIMS ARE WORTH THE NETWORK HERE. `useDayShape(null)` must be an ANSWER rather than a request with no
 * identifier, because nothing selected is a state the screen draws an empty surface for. And a declaration must
 * invalidate the two keys it changes and no others: a blanket revalidation would refetch the habits, the anchor
 * types and every Area on a screen with no animation to hide the flicker. */

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
import {
  ROUTINE_WAKE,
  SHAPE_WEEKDAY,
  buildHabit,
  buildShape,
  buildShapeSummary,
} from "../../routes/templates/__tests__/fixtures";
import { useDayShape, useDayShapes, useEntryDeclaration, type EntryBody } from "./useTemplates";
import { useHabits } from "./useHabits";

const SHAPES = "/api/v1/templates";
const SHAPE = `/api/v1/templates/${SHAPE_WEEKDAY}`;
const ENTRIES = `${SHAPE}/entries`;
const HABITS = "/api/v1/habits";

const entry: EntryBody = {
  kind: "concrete",
  targetTime: "05:00",
  durationMinutes: 15,
  flexBandMinutes: 30,
  bindingTarget: "routine",
  bindingRef: ROUTINE_WAKE,
};

describe("useDayShape", () => {
  it("reads the selected shape with its entries", async () => {
    apiServer.use(jsonHandler(SHAPE, { status: 200, body: buildShape() }));

    const { result } = renderHook(() => useDayShape(SHAPE_WEEKDAY), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("ready"));
    if (result.current.status !== "ready") throw new Error("the reading never settled");
    expect(result.current.data?.entries).toHaveLength(2);
  });

  /* Ready with null rather than loading forever: a hook that reported a pending read for a shape nobody asked
   * for would leave the screen waiting for something that was never requested. */
  it("answers ready with nothing selected, and sends no request", async () => {
    const read = countedHandler(SHAPE, { status: 200, body: buildShape() });
    apiServer.use(read.handler);

    const { result } = renderHook(() => useDayShape(null), { wrapper: FreshCache });

    expect(result.current).toEqual({ status: "ready", data: null });
    await waitFor(() => expect(read.count()).toBe(0));
  });
});

describe("useEntryDeclaration", () => {
  it("sends the entry to the shape that holds it", async () => {
    const write = recordingHandler("post", ENTRIES, { status: 201, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useEntryDeclaration(SHAPE_WEEKDAY), {
      wrapper: FreshCache,
    });
    await expect(result.current.submit(entry)).resolves.toBe(true);

    expect(write.bodies).toEqual([entry]);
  });

  /* The shape holds the entries and the list states a count this changes, so both are named. The habits are
   * not, which is the half a blanket revalidation would get wrong. */
  it("invalidates the shape and the list, and nothing else", async () => {
    const shape = countedHandler(SHAPE, { status: 200, body: buildShape() });
    const shapes = countedHandler(SHAPES, {
      status: 200,
      body: { templates: [buildShapeSummary()] },
    });
    const habits = countedHandler(HABITS, { status: 200, body: { habits: [buildHabit()] } });
    apiServer.use(
      shape.handler,
      shapes.handler,
      habits.handler,
      recordingHandler("post", ENTRIES, { status: 201, body: null }).handler,
    );

    const { result } = renderHook(
      () => ({
        shape: useDayShape(SHAPE_WEEKDAY),
        shapes: useDayShapes(),
        habits: useHabits(),
        write: useEntryDeclaration(SHAPE_WEEKDAY),
      }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.habits.status).toBe("ready"));
    expect([shape.count(), shapes.count(), habits.count()]).toEqual([1, 1, 1]);

    await result.current.write.submit(entry);

    await waitFor(() => expect(shape.count()).toBe(2));
    expect(shapes.count()).toBe(2);
    expect(habits.count()).toBe(1);
  });

  it("keeps the refusal and its named member when the boundary refuses the entry", async () => {
    apiServer.use(
      recordingHandler("post", ENTRIES, {
        status: 422,
        body: {
          type: "syncr:validation-failed",
          title: "Validation failed",
          status: 422,
          detail: "A target time off the quarter hour is not a placement. Nothing was changed.",
          errors: [{ field: "targetTime", message: "must land on a 15-minute step of the grid" }],
        },
      }).handler,
    );

    const { result } = renderHook(() => useEntryDeclaration(SHAPE_WEEKDAY), {
      wrapper: FreshCache,
    });
    await expect(result.current.submit(entry)).resolves.toBe(false);

    await waitFor(() => expect(result.current.problem?.status).toBe(422));
    expect(result.current.problem?.errors?.[0].field).toBe("targetTime");
  });

  /* Reachable only by a caller that renders the editor with nothing selected. Stated rather than silent, so a
   * caller that gets there sees why nothing happened. */
  it("refuses with a stated reason when no shape is selected, and sends nothing", async () => {
    const write = recordingHandler("post", ENTRIES, { status: 201, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useEntryDeclaration(null), { wrapper: FreshCache });
    await expect(result.current.submit(entry)).resolves.toBe(false);

    expect(write.bodies).toEqual([]);
    await waitFor(() => expect(result.current.problem?.title).toBe("No day shape is selected"));
  });

  /* The read half of the same seam: a request that never arrives is a problem with no status, because there is
   * no response to take one from. */
  it("reads an unreachable api as a failure with no status, not as an empty shape", async () => {
    apiServer.use(unreachableHandler(SHAPE));

    const { result } = renderHook(() => useDayShape(SHAPE_WEEKDAY), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("error"));
    if (result.current.status !== "error") throw new Error("the reading never failed");
    expect(result.current.problem.status).toBe(0);
    expect(result.current.problem.detail).toContain("Nothing was sent");
  });

  it("reads a refused shape as a failure carrying the api's own problem", async () => {
    apiServer.use(
      jsonHandler(SHAPE, {
        status: 404,
        body: {
          type: "syncr:not-found",
          title: "Not found",
          status: 404,
          detail: "No day shape matches that identifier.",
        },
      }),
    );

    const { result } = renderHook(() => useDayShape(SHAPE_WEEKDAY), { wrapper: FreshCache });

    await waitFor(() => expect(result.current.status).toBe("error"));
    if (result.current.status !== "error") throw new Error("the reading never failed");
    expect(result.current.problem.detail).toBe("No day shape matches that identifier.");
  });
});
