/* What the settings, off-plan and calendar writes SEND, and which keys each one invalidates.
 *
 * INVALIDATION IS THE CLAIM ONLY A NETWORK TEST CAN MAKE. A mutation invalidates by explicit key rather than by a
 * blanket revalidation, and the only observable difference is WHICH reads run again: counting them is what makes
 * that assertable. A blanket revalidation would refetch the whole week because a feed was excluded, which is both
 * slow and a source of flicker on a surface with no animation to hide it.
 *
 * ONE INVALIDATION HERE IS NOT OBVIOUS AND IS THE REASON THIS FILE EXISTS. A travel override changes `activeZone` on
 * the settings resource, which the request never named: declaring a trip that covers today and leaving the settings
 * key alone would leave the screen stating a zone that is no longer active. */

import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { countedHandler, jsonHandler, recordingHandler } from "../../testing/apiStub";
import { FreshCache } from "../../testing/renderRoute";
import {
  OVERRIDE_BARCELONA,
  PERIOD_LONG_WEEKEND,
  ROUTINE_SLEEP,
  SOURCE_TIMETABLE,
  buildConsent,
  buildOffPlanPeriod,
  buildRoutine,
  buildSettings,
  buildSource,
  buildTravelOverride,
} from "../../routes/settings/__tests__/fixtures";
import {
  useCalendarSources,
  useGoogleConsent,
  useSourceInclusion,
  useSourceSync,
} from "./useCalendarSources";
import { useOffPlanEdit, useOffPlanPeriods, useOffPlanRemoval } from "./useOffPlan";
import { useRoutineEdit } from "./useRoutines";
import {
  useSettings,
  useSettingsPatch,
  useTravelOverrideDeclaration,
  useTravelOverrideRemoval,
  useTravelOverrides,
} from "./useSettings";

const SETTINGS = "/api/v1/settings";
const TRAVEL = `${SETTINGS}/travel-overrides`;
const OFF_PLAN = "/api/v1/off-plan";
const SOURCES = "/api/v1/calendar-sources";
const CONNECT = `${SOURCES}/google/connect`;

describe("useSettingsPatch", () => {
  it("sends only the members it was given, so an omitted field is left alone", async () => {
    const write = recordingHandler("patch", SETTINGS, { status: 200, body: buildSettings() });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useSettingsPatch(), { wrapper: FreshCache });
    await expect(result.current.submit({ visibleHours: 8 })).resolves.toBe(true);

    expect(write.bodies).toEqual([{ visibleHours: 8 }]);
  });

  it("invalidates the settings and nothing else", async () => {
    const settings = countedHandler(SETTINGS, { status: 200, body: buildSettings() });
    const sources = countedHandler(SOURCES, { status: 200, body: { sources: [buildSource()] } });
    apiServer.use(
      settings.handler,
      sources.handler,
      recordingHandler("patch", SETTINGS, { status: 200, body: buildSettings() }).handler,
    );

    const { result } = renderHook(
      () => ({ read: useSettings(), sources: useCalendarSources(), write: useSettingsPatch() }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.read.status).toBe("ready"));
    await waitFor(() => expect(result.current.sources.status).toBe("ready"));
    expect(settings.count()).toBe(1);
    expect(sources.count()).toBe(1);

    await result.current.write.submit({ visibleHours: 8 });

    await waitFor(() => expect(settings.count()).toBe(2));
    expect(sources.count()).toBe(1);
  });

  it("keeps the refusal, so a rejected bound reaches the row the reader is looking at", async () => {
    apiServer.use(
      recordingHandler("patch", SETTINGS, {
        status: 422,
        body: {
          type: "syncr:validation-failed",
          title: "The day has no length",
          status: 422,
          detail: "Day start must be earlier than day end. Nothing was changed.",
        },
      }).handler,
    );

    const { result } = renderHook(() => useSettingsPatch(), { wrapper: FreshCache });
    await expect(result.current.submit({ dayStart: "23:00", dayEnd: "07:00" })).resolves.toBe(
      false,
    );

    await waitFor(() => expect(result.current.problem?.status).toBe(422));
  });
});

describe("a travel override", () => {
  /* The non-obvious one: `activeZone` lives on the settings resource and a trip covering today changes it. */
  it("invalidates the overrides AND the settings, because the active zone lives on the settings", async () => {
    const overrides = countedHandler(TRAVEL, { status: 200, body: { overrides: [] } });
    const settings = countedHandler(SETTINGS, { status: 200, body: buildSettings() });
    apiServer.use(
      overrides.handler,
      settings.handler,
      recordingHandler("post", TRAVEL, { status: 201, body: buildTravelOverride() }).handler,
    );

    const { result } = renderHook(
      () => ({
        overrides: useTravelOverrides(),
        settings: useSettings(),
        write: useTravelOverrideDeclaration(),
      }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.overrides.status).toBe("ready"));
    await waitFor(() => expect(result.current.settings.status).toBe("ready"));

    await result.current.write.submit({
      startDate: "2026-09-01",
      endDate: "2026-09-08",
      zone: "Europe/Madrid",
    });

    await waitFor(() => expect(overrides.count()).toBe(2));
    await waitFor(() => expect(settings.count()).toBe(2));
  });

  it("names its row in the path on a removal, and sends no body", async () => {
    const remove = recordingHandler("delete", `${TRAVEL}/${OVERRIDE_BARCELONA}`, { status: 204 });
    apiServer.use(remove.handler, jsonHandler(TRAVEL, { status: 200, body: { overrides: [] } }));

    const { result } = renderHook(() => useTravelOverrideRemoval(), { wrapper: FreshCache });
    await expect(result.current.submit({ overrideId: OVERRIDE_BARCELONA })).resolves.toBe(true);

    expect(remove.bodies).toEqual([null]);
  });
});

describe("an off-plan period", () => {
  it("patches the row it names, with the members the caller passed", async () => {
    const edit = recordingHandler("patch", `${OFF_PLAN}/${PERIOD_LONG_WEEKEND}`, {
      status: 200,
      body: buildOffPlanPeriod({ keepFrame: true }),
    });
    apiServer.use(edit.handler);

    const { result } = renderHook(() => useOffPlanEdit(), { wrapper: FreshCache });
    await expect(
      result.current.submit({ periodId: PERIOD_LONG_WEEKEND, patch: { keepFrame: true } }),
    ).resolves.toBe(true);

    expect(edit.bodies).toEqual([{ keepFrame: true }]);
  });

  it("invalidates the periods and nothing else on a removal", async () => {
    const periods = countedHandler(OFF_PLAN, { status: 200, body: { periods: [] } });
    const settings = countedHandler(SETTINGS, { status: 200, body: buildSettings() });
    apiServer.use(
      periods.handler,
      settings.handler,
      recordingHandler("delete", `${OFF_PLAN}/${PERIOD_LONG_WEEKEND}`, { status: 204 }).handler,
    );

    const { result } = renderHook(
      () => ({
        periods: useOffPlanPeriods(),
        settings: useSettings(),
        write: useOffPlanRemoval(),
      }),
      { wrapper: FreshCache },
    );
    await waitFor(() => expect(result.current.periods.status).toBe("ready"));
    await waitFor(() => expect(result.current.settings.status).toBe("ready"));

    await result.current.write.submit({ periodId: PERIOD_LONG_WEEKEND });

    await waitFor(() => expect(periods.count()).toBe(2));
    expect(settings.count()).toBe(1);
  });
});

describe("a calendar source", () => {
  it("sends the inclusion the caller asked for, as an absolute value", async () => {
    const patch = recordingHandler("patch", `${SOURCES}/${SOURCE_TIMETABLE}`, {
      status: 200,
      body: buildSource({ included: false }),
    });
    apiServer.use(patch.handler);

    const { result } = renderHook(() => useSourceInclusion(), { wrapper: FreshCache });
    await result.current.submit({ sourceId: SOURCE_TIMETABLE, included: false });

    expect(patch.bodies).toEqual([{ included: false }]);
  });

  /* A forced sync changes an anchor count, and the count changing is how progress is reported, so the read the
   * count comes from is the one key it names. */
  it("invalidates the sources on a forced sync, which is how the count changes", async () => {
    const sources = countedHandler(SOURCES, { status: 200, body: { sources: [buildSource()] } });
    apiServer.use(
      sources.handler,
      recordingHandler("post", `${SOURCES}/${SOURCE_TIMETABLE}/sync`, {
        status: 200,
        body: { id: "op", kind: "calendar_sync", status: "pending" },
      }).handler,
    );

    const { result } = renderHook(() => ({ read: useCalendarSources(), write: useSourceSync() }), {
      wrapper: FreshCache,
    });
    await waitFor(() => expect(result.current.read.status).toBe("ready"));

    await result.current.write.submit({ sourceId: SOURCE_TIMETABLE });

    await waitFor(() => expect(sources.count()).toBe(2));
  });
});

/* A FLOOR'S ONE HOME. The hook is a routine edit and takes the routine it is addressed to, because the floor is a
 * field on every routine and no routine carries a marker singling it out. */
describe("useRoutineEdit", () => {
  it("patches the routine it was given", async () => {
    const write = recordingHandler("patch", `/api/v1/routines/${ROUTINE_SLEEP}`, {
      status: 200,
      body: buildRoutine({ minDurationMinutes: 390 }),
    });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useRoutineEdit(ROUTINE_SLEEP), { wrapper: FreshCache });
    await expect(result.current.submit({ minDurationMinutes: 390 })).resolves.toBe(true);

    expect(write.bodies).toEqual([{ minDurationMinutes: 390 }]);
  });

  it("refuses with a stated reason when no routine is named, and sends nothing", async () => {
    const write = recordingHandler("patch", `/api/v1/routines/${ROUTINE_SLEEP}`, {
      status: 200,
      body: buildRoutine(),
    });
    apiServer.use(write.handler);

    const { result } = renderHook(() => useRoutineEdit(null), { wrapper: FreshCache });
    await expect(result.current.submit({ minDurationMinutes: 390 })).resolves.toBe(false);

    expect(write.bodies).toEqual([]);
    await waitFor(() => expect(result.current.problem?.title).toBe("No routine is selected"));
  });
});

/* ASKING FOR CONSENT MINTS STATE, so it is a request a reader makes rather than one a render makes. */
describe("useGoogleConsent", () => {
  it("answers with the surface, so the scopes can be read before the reader leaves", async () => {
    apiServer.use(recordingHandler("post", CONNECT, { status: 200, body: buildConsent() }).handler);

    const { result } = renderHook(() => useGoogleConsent(), { wrapper: FreshCache });
    const consent = await result.current.begin();

    expect(consent?.authorizationUrl).toContain("accounts.google.com");
    await waitFor(() => expect(result.current.consent?.scopes).toHaveLength(1));
  });

  it("keeps the api's refusal and answers with nothing", async () => {
    apiServer.use(
      recordingHandler("post", CONNECT, {
        status: 503,
        body: {
          type: "syncr:dependency-unavailable",
          title: "Google is not configured",
          status: 503,
          detail: "This deployment has no Google client. ICS feeds are unaffected.",
        },
      }).handler,
    );

    const { result } = renderHook(() => useGoogleConsent(), { wrapper: FreshCache });
    await expect(result.current.begin()).resolves.toBeNull();

    await waitFor(() =>
      expect(result.current.problem?.detail).toBe(
        "This deployment has no Google client. ICS feeds are unaffected.",
      ),
    );
  });
});
