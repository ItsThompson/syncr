/* The reads the setup ledger and the root redirect are built on, as handlers.
 *
 * ONE PLACE FOR THE FOUR HANDLERS, because both the setup route and the root redirect make the same four reads and a
 * second copy of the set is how one of them comes to stub three. Each helper takes the counts the case is about. */

import type { RequestHandler } from "msw";

import { jsonHandler } from "../../../testing/apiStub";
import { buildSource, buildWriteTarget } from "../../settings/__tests__/fixtures";

export interface SetupState {
  readonly sources: number;
  readonly areas: number;
  readonly shapes: number;
  readonly isPatternDeclared: boolean;
  readonly hasWriteTarget?: boolean;
}

/** Nothing declared, which is the state a brand-new tenant reads as. */
export const NOTHING_DECLARED: SetupState = {
  sources: 0,
  areas: 0,
  shapes: 0,
  isPatternDeclared: false,
};

/** The minimum a plan needs, and nothing optional. */
export const MINIMUM_DECLARED: SetupState = {
  sources: 0,
  areas: 2,
  shapes: 1,
  isPatternDeclared: true,
};

const WEEKDAYS = [
  "monday",
  "tuesday",
  "wednesday",
  "thursday",
  "friday",
  "saturday",
  "sunday",
] as const;

const DAY_TYPE = "8a1d5f20-0100-4b7e-9c31-0000000000d1";

function areaAt(index: number) {
  return {
    id: `8a1d5f20-02${String(index).padStart(2, "0")}-4b7e-9c31-0000000000a1`,
    parentId: null,
    name: `Area ${index + 1}`,
    pigmentIndex: index,
    budgetPercent: null,
    floorHours: null,
  };
}

function shapeAt(index: number) {
  return {
    id: `8a1d5f20-03${String(index).padStart(2, "0")}-4b7e-9c31-0000000000s1`,
    dayTypeId: DAY_TYPE,
    name: `Shape ${index + 1}`,
    entryCount: 2,
  };
}

/** Every read the setup ledger makes, stubbed for one state. */
export function setupHandlers(state: SetupState): RequestHandler[] {
  const sources = Array.from({ length: state.sources }, (_unused, index) =>
    buildSource({ id: `8a1d5f20-01${String(index).padStart(2, "0")}-4b7e-9c31-0000000000c1` }),
  );
  if (state.hasWriteTarget === true) sources.push(buildWriteTarget());

  return [
    jsonHandler("/api/v1/areas", {
      status: 200,
      body: {
        areas: Array.from({ length: state.areas }, (_unused, index) => areaAt(index)),
        ramp: {
          pigmentCount: 12,
          pigmentsInUse: state.areas,
          areasSharingAPigment: 0,
          statement: null,
        },
      },
    }),
    jsonHandler("/api/v1/templates", {
      status: 200,
      body: { templates: Array.from({ length: state.shapes }, (_unused, index) => shapeAt(index)) },
    }),
    jsonHandler(
      "/api/v1/week-pattern",
      state.isPatternDeclared
        ? {
            status: 200,
            body: Object.fromEntries(WEEKDAYS.map((weekday) => [weekday, DAY_TYPE])),
          }
        : {
            status: 404,
            body: {
              type: "syncr:not-found",
              title: "No week pattern is declared",
              status: 404,
              detail: "Declare one, and every weekday maps to a kind of day.",
            },
          },
    ),
    jsonHandler("/api/v1/calendar-sources", { status: 200, body: { sources } }),
  ];
}
