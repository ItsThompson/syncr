/* The two writes on an anchor type, and the one on a habit.
 *
 * Both files' reads are the same shape as every other list read and are exercised through the screens. What only
 * a network test can say is what the writes SEND and what they invalidate: a patch carries absolute values to
 * one type, a reorder carries the whole order, and both name the one key they change. */

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, recordingHandler } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import {
  HABIT_GYM,
  TYPE_INTERVIEW,
  TYPE_LECTURE,
  buildAnchorType,
  buildHabit,
  buildLectureType,
  buildPrepCollision,
} from "../../routes/templates/__tests__/fixtures";
import { useAnchorTypeEdit, useAnchorTypeOrder, useAnchorTypes } from "./useAnchorTypes";
import { useHabitEdit, useHabits } from "./useHabits";

const TYPES = "/api/v1/anchor-types";
const TYPE = `${TYPES}/${TYPE_INTERVIEW}`;
const ORDER = `${TYPES}/order`;
const HABITS = "/api/v1/habits";
const HABIT = `${HABITS}/${HABIT_GYM}`;

const typesBody = { anchorTypes: [buildAnchorType(), buildLectureType()] };

describe("useAnchorTypeEdit", () => {
  it("patches the type it was given, with the geometry it was handed", async () => {
    const write = recordingHandler("patch", TYPE, { status: 200, body: buildAnchorType() });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useAnchorTypeEdit(TYPE_INTERVIEW), { wrapper: FreshCache });
    await expect(result.current.submit({ prepLeadMinutes: 375 })).resolves.toBe(true);

    expect(write.bodies).toEqual([{ prepLeadMinutes: 375 }]);
  });

  it("invalidates the rules, so the table redraws with the new geometry", async () => {
    const read = countedHandler(TYPES, { status: 200, body: typesBody });
    apiServer.use(
      read.handler,
      recordingHandler("patch", TYPE, { status: 200, body: null }).handler,
    );

    const { result } = renderHook(
      () => ({ types: useAnchorTypes(), write: useAnchorTypeEdit(TYPE_INTERVIEW) }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.types.status).toBe("ready"));
    expect(read.count()).toBe(1);

    await result.current.write.submit({ prepLeadMinutes: 375 });

    await waitFor(() => expect(read.count()).toBe(2));
  });

  /* The refusal a reader has to see: the prep-lead collision, named on the member to change. */
  it("keeps the collision refusal and the member it names", async () => {
    apiServer.use(
      recordingHandler("patch", TYPE, { status: 422, body: buildPrepCollision() }).handler,
    );

    const { result } = renderHook(() => useAnchorTypeEdit(TYPE_INTERVIEW), { wrapper: FreshCache });
    await expect(result.current.submit({ prepLeadMinutes: 15 })).resolves.toBe(false);

    await waitFor(() => expect(result.current.problem?.errors?.[0].field).toBe("prepLeadMinutes"));
  });

  it("refuses with a stated reason when no type is selected, and sends nothing", async () => {
    const write = recordingHandler("patch", TYPE, { status: 200, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useAnchorTypeEdit(null), { wrapper: FreshCache });
    await expect(result.current.submit({ prepLeadMinutes: 375 })).resolves.toBe(false);

    expect(write.bodies).toEqual([]);
    await waitFor(() => expect(result.current.problem?.title).toBe("No anchor type is selected"));
  });
});

describe("useAnchorTypeOrder", () => {
  it("sends the whole order, because a partial one would move rules the caller cannot see", async () => {
    const write = recordingHandler("put", ORDER, { status: 200, body: typesBody });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useAnchorTypeOrder(), { wrapper: FreshCache });
    await expect(
      result.current.submit({ anchorTypeIds: [TYPE_LECTURE, TYPE_INTERVIEW] }),
    ).resolves.toBe(true);

    expect(write.bodies).toEqual([{ anchorTypeIds: [TYPE_LECTURE, TYPE_INTERVIEW] }]);
  });

  it("invalidates the rules, because reordering re-evaluates what every one of them matches", async () => {
    const read = countedHandler(TYPES, { status: 200, body: typesBody });
    apiServer.use(
      read.handler,
      recordingHandler("put", ORDER, { status: 200, body: null }).handler,
    );

    const { result } = renderHook(
      () => ({ types: useAnchorTypes(), write: useAnchorTypeOrder() }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.types.status).toBe("ready"));

    await result.current.write.submit({ anchorTypeIds: [TYPE_LECTURE, TYPE_INTERVIEW] });

    await waitFor(() => expect(read.count()).toBe(2));
  });
});

describe("useHabitEdit", () => {
  it("patches the habit it was given", async () => {
    const write = recordingHandler("patch", HABIT, { status: 200, body: buildHabit() });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useHabitEdit(HABIT_GYM), { wrapper: FreshCache });
    await expect(result.current.submit({ title: "Gym" })).resolves.toBe(true);

    expect(write.bodies).toEqual([{ title: "Gym" }]);
  });

  it("invalidates the habits, and leaves the anchor types alone", async () => {
    const habits = countedHandler(HABITS, { status: 200, body: { habits: [buildHabit()] } });
    const types = countedHandler(TYPES, { status: 200, body: typesBody });
    apiServer.use(
      habits.handler,
      types.handler,
      recordingHandler("patch", HABIT, { status: 200, body: null }).handler,
    );

    const { result } = renderHook(
      () => ({ habits: useHabits(), types: useAnchorTypes(), write: useHabitEdit(HABIT_GYM) }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.types.status).toBe("ready"));

    await result.current.write.submit({ title: "Gym" });

    await waitFor(() => expect(habits.count()).toBe(2));
    expect(types.count()).toBe(1);
  });

  it("refuses with a stated reason when no habit is selected, and sends nothing", async () => {
    const write = recordingHandler("patch", HABIT, { status: 200, body: null });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useHabitEdit(null), { wrapper: FreshCache });
    await expect(result.current.submit({ title: "Gym" })).resolves.toBe(false);

    expect(write.bodies).toEqual([]);
    await waitFor(() => expect(result.current.problem?.title).toBe("No habit is selected"));
  });
});
