/* `/settings` as a reader meets it.
 *
 * FOUR CLAIMS ARE ASSERTED HERE and each is a rule rather than a rendering detail: a floor writes to the routine it
 * belongs to and never to the settings endpoint, the clamped zoom control offers its unavailable levels rather than
 * hiding them, every error panel names what still works, and no spinner or progress bar appears anywhere on the
 * screen.
 *
 * THE WRITE ASSERTIONS ARE ABOUT THE REQUEST, not about a mocked hook. The recording handlers answer for a path, so
 * what is asserted is the path the client went to and the members it carried, which is the whole contract of a write.
 *
 * THE PROGRESS-BAR CLAIM IS ASSERTED BY ROLE, so a bar added later fails it whichever component drew one. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { authoredNames } from "../../../testing/accessibleNames";
import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, recordingHandler } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import { MIN_FLOOR_MINUTES } from "../routineFloor";
import {
  NOW,
  ROUTINE_NAP,
  ROUTINE_SLEEP,
  SOURCE_PLAN,
  buildConnection,
  buildExpiryNotices,
  buildLunch,
  buildNap,
  buildOffPlanPeriod,
  buildRoutine,
  buildSettings,
  buildSource,
  buildSyncState,
  buildTravelOverride,
  buildWriteTarget,
} from "./fixtures";
import { settingsHandlers } from "./handlers";

const SETTINGS = "/api/v1/settings";
const TRAVEL = "/api/v1/settings/travel-overrides";
const OFF_PLAN = "/api/v1/off-plan";
const FIRST_ROUTINE = `/api/v1/routines/${ROUTINE_SLEEP}`;
const SECOND_ROUTINE = `/api/v1/routines/${ROUTINE_NAP}`;
const HORIZON = `/api/v1/calendar-sources/${SOURCE_PLAN}/horizon`;

const HOUR = 60 * 60 * 1000;

/** The screen is settled once the sources table has drawn, which is the first panel to need a read. */
async function settled(): Promise<void> {
  await waitFor(() => expect(screen.getByRole("table", { name: /Anchor sources/ })).toBeVisible());
}

const panelNamed = (title: string) => screen.getByRole("region", { name: new RegExp(title, "i") });

/** What a field is described by, which is the hint a reader is given without opening the control. */
const hintOf = (field: HTMLElement): string | null => {
  const messageId = field.getAttribute("aria-describedby");
  if (messageId === null) return null;
  return document.getElementById(messageId)?.textContent ?? null;
};

/* The same condition is raised at two volumes with a shared identity root: a banner in the top bar and a panel at
 * the head of this screen. They carry the same title by design, so a query for one has to say which volume. */
const noticeAt = (volume: "panel" | "banner", role: "alert" | "status", name: string) => {
  const found = screen
    .getAllByRole(role, { name })
    .filter((element) => element.className.includes(`notice--${volume}`));
  expect(found).toHaveLength(1);
  return found[0] as HTMLElement;
};

describe("the anchor sources table", () => {
  it("states each source's provider, anchor count, last sync and state", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const row = within(screen.getByRole("table", { name: /Anchor sources/ })).getByRole("row", {
      name: /Timetable/,
    });

    expect(row).toHaveTextContent("ics");
    expect(row).toHaveTextContent("42");
    expect(row).toHaveTextContent("2026-08-05");
    expect(row).toHaveTextContent("ok");
  });

  it("renders a source that has never synced as never rather than as a blank", async () => {
    apiServer.use(
      ...settingsHandlers({
        sources: [
          buildSource({
            state: "never-synced",
            anchorCount: 0,
            syncState: buildSyncState({ lastSuccessAt: null, lastAttemptAt: null, eventsRead: 0 }),
          }),
        ],
      }),
    );
    renderAt("/settings");
    await settled();

    expect(
      within(screen.getByRole("table", { name: /Anchor sources/ })).getByRole("row", {
        name: /Timetable/,
      }),
    ).toHaveTextContent("never");
  });

  it("offers include, exclude, remove and sync on each row", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    expect(screen.getByRole("button", { name: "Exclude" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sync" })).toBeInTheDocument();
  });

  it("offers Include on an excluded source, and reports excluded as a state rather than an error", async () => {
    apiServer.use(
      ...settingsHandlers({
        sources: [buildSource({ included: false, state: "excluded", anchorCount: 0 })],
      }),
    );
    renderAt("/settings");
    await settled();

    expect(screen.getByRole("button", { name: "Include" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: /Anchor sources/ })).getByRole("row", {
        name: /Timetable/,
      }),
    ).toHaveTextContent("excluded");
  });

  /* A count that changes is how sync progress is reported. There is nothing to spin and nothing in the kit to spin
   * with, so the report is the anchor count in the row being different after the read. */
  it("reports a sync by the anchor count changing, not by a spinner", async () => {
    const sync = recordingHandler("post", `/api/v1/calendar-sources/${buildSource().id}/sync`, {
      status: 200,
      body: { id: "op", kind: "calendar_sync", status: "pending" },
    });
    let answered = 0;
    apiServer.use(
      sync.handler,
      jsonHandler("/api/v1/calendar-sources", { status: 200, body: { sources: [] } }),
      ...settingsHandlers(),
    );
    apiServer.use(
      /* Answers 42 first and 57 afterwards, so the count is observably different after the write. */
      jsonHandler("/api/v1/calendar-sources", { status: 200, body: { sources: [buildSource()] } }),
    );
    apiServer.events.on("request:start", ({ request }) => {
      if (request.url.endsWith("/api/v1/calendar-sources")) answered += 1;
    });
    renderAt("/settings");
    await settled();

    apiServer.use(
      jsonHandler("/api/v1/calendar-sources", {
        status: 200,
        body: { sources: [buildSource({ anchorCount: 57 })] },
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Sync" }));

    await waitFor(() => expect(screen.getByText("57")).toBeInTheDocument());
    expect(answered).toBeGreaterThan(1);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});

describe("the write target", () => {
  it("names the calendar, the horizon and the reconciliation behaviour", async () => {
    apiServer.use(...settingsHandlers({ sources: [buildSource(), buildWriteTarget()] }));
    renderAt("/settings");
    await settled();

    /* Each value is asked for by its own term, because the api's statement in this panel also contains
       `14 days`: an assertion over the panel's whole text would match that sentence and never read the rows. */
    const panel = panelNamed("Write target");
    expect(within(panel).getByRole("definition", { name: "calendar" })).toHaveTextContent(
      "syncr \u00b7 plan",
    );
    expect(within(panel).getByRole("definition", { name: "horizon" })).toHaveTextContent("14 days");
    expect(within(panel).getByRole("definition", { name: "reconciliation" })).toHaveTextContent(
      "destructive",
    );
  });

  /* The most consequential fact on this screen, and it is the api's own sentence: whatever renders the write target
   * renders it, so a second surface cannot forget to say it. */
  it("states that the target is reconciled destructively and that a client edit is overwritten", async () => {
    apiServer.use(...settingsHandlers({ sources: [buildWriteTarget()] }));
    renderAt("/settings");
    await settled();

    expect(panelNamed("Write target")).toHaveTextContent(
      "an event you edit in a calendar client is overwritten on the next write",
    );
  });

  it("sets the horizon in days, from a field that starts at the stored 14", async () => {
    const horizon = recordingHandler("patch", HORIZON, { status: 200, body: buildWriteTarget() });
    apiServer.use(horizon.handler, ...settingsHandlers({ sources: [buildWriteTarget()] }));
    renderAt("/settings");
    await settled();

    const field = screen.getByRole("textbox", { name: /Horizon/ });
    expect(field).toHaveValue("14");

    await userEvent.clear(field);
    await userEvent.type(field, "21");
    await userEvent.click(screen.getByRole("button", { name: "Set the horizon" }));

    await waitFor(() => expect(horizon.bodies).toEqual([{ horizonDays: 21 }]));
  });

  it("offers a designation while no calendar holds the role, and says what that costs", async () => {
    apiServer.use(...settingsHandlers({ sources: [buildSource()] }));
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Write target");
    expect(panel).toHaveTextContent("No calendar holds the write-target role");
    expect(panel).toHaveTextContent("nothing reaches your phone");
    expect(
      within(panel).getByRole("button", { name: "Designate the write target" }),
    ).toBeInTheDocument();
  });

  it("renders the api's refusal of a second write target rather than predicting the rule", async () => {
    apiServer.use(
      recordingHandler("put", `/api/v1/calendar-sources/${buildSource().id}/role`, {
        status: 409,
        body: {
          type: "syncr:conflict",
          title: "A write target already exists",
          status: 409,
          detail:
            "syncr \u00b7 plan already holds the write-target role. Remove it from that calendar first; " +
            "nothing was changed and the plan still reaches it.",
        },
      }).handler,
      ...settingsHandlers({ sources: [buildSource()] }),
    );
    renderAt("/settings");
    await settled();

    await userEvent.click(screen.getByRole("button", { name: "Designate the write target" }));

    expect(await screen.findByText(/already holds the write-target role/)).toBeInTheDocument();
  });
});

describe("the zone and travel panel", () => {
  it("states the active zone and the date it was resolved for", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    expect(panelNamed("Zone and travel")).toHaveTextContent("Europe/London \u00b7 on 2026-08-05");
  });

  it("says an override is in force, naming its range, when one covers the resolved date", async () => {
    apiServer.use(
      ...settingsHandlers({
        settings: buildSettings({ activeZone: "Europe/Madrid" }),
        overrides: [buildTravelOverride({ startDate: "2026-08-01", endDate: "2026-08-09" })],
      }),
    );
    renderAt("/settings");
    await settled();

    expect(panelNamed("Zone and travel")).toHaveTextContent(
      "A travel override covers today, 2026-08-01 to 2026-08-09",
    );
  });

  /* THE CASE A ZONE COMPARISON GETS WRONG. The api accepts an override whose zone is the home zone, so
     `activeZone !== homeZone` reports that nothing covers today while a declared range does. */
  it("says an override is in force even when it names the home zone", async () => {
    apiServer.use(
      ...settingsHandlers({
        overrides: [
          buildTravelOverride({
            startDate: "2026-08-01",
            endDate: "2026-08-09",
            zone: "Europe/London",
          }),
        ],
      }),
    );
    renderAt("/settings");
    await settled();

    expect(panelNamed("Zone and travel")).toHaveTextContent("A travel override covers today");
  });

  it("lists each override with its range and zone, and offers a removal", async () => {
    apiServer.use(...settingsHandlers({ overrides: [buildTravelOverride()] }));
    renderAt("/settings");
    await settled();

    const table = screen.getByRole("table", { name: /Travel overrides/ });
    expect(table).toHaveTextContent("2026-09-01");
    expect(table).toHaveTextContent("2026-09-08");
    expect(table).toHaveTextContent("Europe/Madrid");
    expect(within(table).getByRole("button", { name: "Remove" })).toBeInTheDocument();
  });

  it("says the home zone is in force where no override covers the resolved date", async () => {
    apiServer.use(...settingsHandlers({ overrides: [buildTravelOverride()] }));
    renderAt("/settings");
    await settled();

    expect(panelNamed("Zone and travel")).toHaveTextContent(
      "No travel override covers today, so the active zone is your home zone",
    );
  });

  /* An overlapping declaration is rejected at the boundary with a stated reason, and the reason is the api's: a
   * client-side pre-check would be a second copy of a rule the api owns. */
  it("renders the boundary rejection of an overlapping declaration with its stated reason", async () => {
    apiServer.use(
      recordingHandler("post", TRAVEL, {
        status: 409,
        body: {
          type: "syncr:conflict",
          title: "Travel overrides overlap",
          status: 409,
          detail:
            "2026-09-01 to 2026-09-08 and 2026-09-05 to 2026-09-12 cover a common date. Nothing was " +
            "declared; every other override still reads as it did.",
        },
      }).handler,
      ...settingsHandlers({ overrides: [buildTravelOverride()] }),
    );
    renderAt("/settings");
    await settled();

    await userEvent.click(screen.getByRole("button", { name: "Declare travel" }));

    expect(await screen.findByText(/cover a common date/)).toBeInTheDocument();
  });
});

describe("the grid geometry panel", () => {
  it("offers the visible-hours levels, with the ones past the display's cap marked unavailable", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    await userEvent.click(screen.getByRole("combobox", { name: /Visible hours/ }));

    const unavailable = screen.getByRole("option", { name: /24 hours/ });
    expect(unavailable).toHaveTextContent("unavailable on this display");
    expect(unavailable).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByRole("option", { name: /^12 hours$/ })).not.toHaveAttribute(
      "aria-disabled",
      "true",
    );
  });

  /* THE WHOLE HINT BY EQUALITY, AND READ THROUGH THE FIELD'S OWN `aria-describedby`. The claim is that a reader is
   * told which of two figures they have been handed, so the reading has to be the sentence the field points at
   * rather than text anywhere in the panel, and equality is what refuses a clause quietly dropped from the middle
   * of it. `geometry.test.ts` owns the words; what this case owns is that they reach the control.
   *
   * THE WINDOW IS SET rather than inherited. jsdom reports 768px, whose cap is 13; at the height `--grid-h` is
   * stated against the sentence names the 16 the display record measured, which is the figure the arithmetic is
   * pinned at one file over. */
  it("names the cap in the field's own hint, and says the figure is an estimate", async () => {
    const inherited = Object.getOwnPropertyDescriptor(window, "innerHeight");
    Object.defineProperty(window, "innerHeight", { configurable: true, value: 900 });
    try {
      apiServer.use(...settingsHandlers());
      renderAt("/settings");
      await settled();

      expect(hintOf(screen.getByRole("combobox", { name: /Visible hours/ }))).toBe(
        "How much of a day the Week grid shows at once. Past 16 hours a 30-minute block is too short " +
          "to hold its title on this display, and that is the most common block length by a wide " +
          "margin. Those levels are listed as unavailable rather than removed, so the range reads as a " +
          "range. This screen is not rendering that grid, so the figure is estimated from this window. " +
          "The Week screen measures its own grid and may allow a different level.",
      );
    } finally {
      if (inherited !== undefined) Object.defineProperty(window, "innerHeight", inherited);
    }
  });

  it("writes the chosen level to the settings endpoint", async () => {
    const patch = recordingHandler("patch", SETTINGS, {
      status: 200,
      body: buildSettings({ visibleHours: 8 }),
    });
    apiServer.use(patch.handler, ...settingsHandlers());
    renderAt("/settings");
    await settled();

    await userEvent.click(screen.getByRole("combobox", { name: /Visible hours/ }));
    await userEvent.click(screen.getByRole("option", { name: /^8 hours$/ }));

    await waitFor(() => expect(patch.bodies).toEqual([{ visibleHours: 8 }]));
  });

  /* Day bounds are a default extent and never a crop, and the screen states the effect on the Week grid rather
   * than leaving it to be discovered after a block vanishes. */
  it("labels the day bounds as where the axis starts, never where it stops", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Grid geometry");
    expect(panel).toHaveTextContent(
      "Where the Week grid's axis STARTS by default, never where it stops",
    );
    expect(panel).toHaveTextContent("widens the axis rather than being hidden");
  });

  it("states the effect of both settings on the Week grid, and that neither needs a reload", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Grid geometry");
    expect(panel).toHaveTextContent("expands to contain every block in the week being read");
    expect(panel).toHaveTextContent("with no reload");
  });

  /* The interval is named by the words the row draws: a reader asking for "Day bounds" reaches the fieldset,
   * and the words were written once rather than drawn on the screen and again as the control's own string. */
  it("names the day bounds interval by the words the screen draws, written once", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Grid geometry");
    const interval = within(panel).getByLabelText("Day bounds");

    expect(interval.tagName).toBe("FIELDSET");
    expect(interval).not.toHaveAttribute("aria-label");
    expect(authoredNames(panel, "Day bounds")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);

    /* The row's hint reaches the fields through the id the row hands over, so a reader gets it without
     * opening either end. */
    expect(within(panel).getByLabelText("from")).toHaveAccessibleDescription(
      expect.stringContaining("Where the Week grid's axis STARTS"),
    );
  });

  /* The wall time that reaches the api names no zone and carries no seconds: the zone comes from the day being
   * rendered, and a column with no offset would drop one in silence.
   *
   * `fireEvent.change` RATHER THAN `userEvent.type`, and that is the whole point of the case. The kit's time input
   * snaps on blur, so a typed value is already on the grid by the time a click reaches the button and this panel's
   * own snap would be a no-op the test could not see. Changing the value without focusing it is what leaves an
   * unsnapped figure in state, which is the state a submit has to correct. */
  it("sends the day bounds as bare wall times, snapped to the quarter hour", async () => {
    const patch = recordingHandler("patch", SETTINGS, { status: 200, body: buildSettings() });
    apiServer.use(patch.handler, ...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Grid geometry");
    fireEvent.change(within(panel).getByLabelText("from"), { target: { value: "06:07" } });
    fireEvent.click(screen.getByRole("button", { name: "Set the day bounds" }));

    await waitFor(() => expect(patch.bodies).toEqual([{ dayStart: "06:00", dayEnd: "23:00" }]));
  });

  it("takes effect on the next render, with the panel reading the new figure and no reload", async () => {
    apiServer.use(
      recordingHandler("patch", SETTINGS, { status: 200, body: buildSettings({ visibleHours: 8 }) })
        .handler,
      ...settingsHandlers(),
    );
    renderAt("/settings");
    await settled();

    expect(panelNamed("Grid geometry")).toHaveTextContent("At 12 hours the grid shows");

    apiServer.use(jsonHandler(SETTINGS, { status: 200, body: buildSettings({ visibleHours: 8 }) }));
    await userEvent.click(screen.getByRole("combobox", { name: /Visible hours/ }));
    await userEvent.click(screen.getByRole("option", { name: /^8 hours$/ }));

    await waitFor(() =>
      expect(panelNamed("Grid geometry")).toHaveTextContent("At 8 hours the grid shows"),
    );
  });

  it("renders the api's refusal of bounds with no length rather than predicting it", async () => {
    apiServer.use(
      recordingHandler("patch", SETTINGS, {
        status: 422,
        body: {
          type: "syncr:validation-failed",
          title: "The day has no length",
          status: 422,
          detail:
            "The day starts at 23:00 and ends at 07:00, so it has no length. Day start must be earlier " +
            "than day end. Nothing was changed; every other setting still reads as it did.",
        },
      }).handler,
      ...settingsHandlers(),
    );
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Grid geometry");
    const from = within(panel).getByLabelText("from");
    await userEvent.clear(from);
    await userEvent.type(from, "23:00");
    const to = within(panel).getByLabelText("to");
    await userEvent.clear(to);
    await userEvent.type(to, "07:00");
    await userEvent.click(screen.getByRole("button", { name: "Set the day bounds" }));

    expect(await screen.findByText(/so it has no length/)).toBeInTheDocument();
  });
});

/* ONE HOME FOR THE VALUE, AND ONE CONTROL PER ROUTINE. A floor is `minDurationMinutes` on the routine it belongs to
 * and the settings endpoint does not carry it, so the assertions are about WHICH path a write went to and which
 * routine it addressed. No case here reaches a control by a routine's title, because a title identifies nothing:
 * the first case titles the only routine something else entirely and still expects a floor. */
describe("the routine floors", () => {
  it("offers a floor whatever the routine is titled, and patches that routine", async () => {
    const routine = recordingHandler("patch", FIRST_ROUTINE, {
      status: 200,
      body: buildRoutine({ title: "Kip", minDurationMinutes: 465 }),
    });
    const settings = recordingHandler("patch", SETTINGS, { status: 200, body: buildSettings() });
    apiServer.use(
      routine.handler,
      settings.handler,
      ...settingsHandlers({ routines: [buildRoutine({ title: "Kip" })] }),
    );
    renderAt("/settings");
    await settled();

    expect(screen.getByLabelText("Kip · 23:00")).toBeVisible();

    await userEvent.click(
      within(panelNamed("Routine floors")).getByRole("button", { name: "decrease 15 minutes" }),
    );

    await waitFor(() => expect(routine.bodies).toEqual([{ minDurationMinutes: 465 }]));
    expect(settings.bodies).toEqual([]);
  });

  /* Two routines may share a title, so a reader has to be able to reach both, and each control has to write to its
     own routine rather than to whichever one the screen found first. */
  it("reaches both routines where two share a title", async () => {
    const first = recordingHandler("patch", FIRST_ROUTINE, { status: 200, body: buildRoutine() });
    const second = recordingHandler("patch", SECOND_ROUTINE, { status: 200, body: buildNap() });
    apiServer.use(
      first.handler,
      second.handler,
      ...settingsHandlers({ routines: [buildRoutine(), buildNap()] }),
    );
    renderAt("/settings");
    await settled();

    expect(screen.getByLabelText("Sleep · 23:00")).toBeVisible();
    expect(screen.getByLabelText("Sleep · 14:00")).toBeVisible();

    await userEvent.click(
      within(panelNamed("Routine floors")).getAllByRole("button", {
        name: "decrease 15 minutes",
      })[1] as HTMLElement,
    );

    await waitFor(() => expect(second.bodies).toEqual([{ minDurationMinutes: 15 }]));
    expect(first.bodies).toEqual([]);
  });

  it("marks the routines the solver may propose shortening, from the floor and the target", async () => {
    apiServer.use(
      ...settingsHandlers({ routines: [buildRoutine({ minDurationMinutes: 390 }), buildLunch()] }),
    );
    renderAt("/settings");
    await settled();

    expect(screen.getByText(/Negotiable: the floor is below the target of 8h/)).toBeVisible();
    expect(screen.getByText(/Not negotiable: the floor equals the target of 45m/)).toBeVisible();
  });

  it("says there is nothing to set where no routine is declared, and what still works", async () => {
    apiServer.use(...settingsHandlers({ routines: [] }));
    renderAt("/settings");
    await settled();

    expect(screen.getByText("No routines are declared")).toBeVisible();
    const panel = panelNamed("Routine floors");
    expect(panel).toHaveTextContent("a week still solves");
    expect(within(panel).queryByRole("spinbutton")).not.toBeInTheDocument();
  });

  it("bounds each control by its own routine's target duration", async () => {
    apiServer.use(...settingsHandlers({ routines: [buildRoutine(), buildLunch()] }));
    renderAt("/settings");
    await settled();

    expect(screen.getByLabelText("Sleep · 23:00")).toHaveAttribute("max", "480");
    expect(screen.getByLabelText("Lunch · 13:00")).toHaveAttribute("max", "45");
    expect(panelNamed("Routine floors")).toBeVisible();
  });

  /* The floor is held when a figure is committed rather than by the element, so what reaches the api is what
     that bound produced and not what the control was stepped to. */
  it("holds the api's own floor rather than sending a figure below it", async () => {
    const routine = recordingHandler("patch", FIRST_ROUTINE, {
      status: 200,
      body: buildRoutine({ minDurationMinutes: MIN_FLOOR_MINUTES }),
    });
    apiServer.use(
      routine.handler,
      ...settingsHandlers({ routines: [buildRoutine({ minDurationMinutes: 10 })] }),
    );
    renderAt("/settings");
    await settled();

    await userEvent.click(
      within(panelNamed("Routine floors")).getByRole("button", { name: "decrease 15 minutes" }),
    );

    await waitFor(() =>
      expect(routine.bodies).toEqual([{ minDurationMinutes: MIN_FLOOR_MINUTES }]),
    );
  });

  /* A TYPED FIGURE REACHES THE API UNCLAMPED, which the stepper documents as deliberate, so this control can be
     refused by a bound the read it was drawn from no longer states. The refusal is the api's own sentence, it
     belongs to the field that caused it, and it belongs to THAT row: the panel renders one write per row so a
     refused floor cannot appear under a routine the reader never touched. */
  it("states the api's refusal under the routine that caused it, and under no other", async () => {
    const refused = {
      type: "syncr:validation-failed",
      title: "Validation failed",
      status: 422,
      detail:
        "The routine was not accepted: a routine's minimum is above 0 and at most its target duration of 30 " +
        "minutes, got 45. Nothing was changed, and every routine that already exists still reads as it did. A " +
        "target and a floor are legal only with respect to each other, so send both in one request when both " +
        "have to move.",
      errors: [
        {
          field: "minDurationMinutes",
          message:
            "a routine's minimum is above 0 and at most its target duration of 30 minutes, got 45",
        },
      ],
    };
    apiServer.use(
      recordingHandler("patch", SECOND_ROUTINE, { status: 422, body: refused }).handler,
      ...settingsHandlers({ routines: [buildRoutine(), buildNap()] }),
    );
    renderAt("/settings");
    await settled();

    fireEvent.change(screen.getByLabelText("Sleep · 14:00"), { target: { value: "45" } });

    const refusal = await screen.findByText(/at most its target duration of 30 minutes, got 45\./);
    expect(refusal).toBeVisible();
    expect(screen.getAllByText(/at most its target duration of 30 minutes, got 45\./)).toHaveLength(
      1,
    );

    const refusedField = screen.getByLabelText("Sleep · 14:00");
    expect(refusedField).toHaveAttribute("aria-invalid", "true");
    expect(refusedField).toHaveAccessibleDescription(/at most its target duration of 30 minutes/);

    /* The other row is untouched: not marked invalid, and still described by its own reading rather than by a
       refusal it did not cause. */
    const untouched = screen.getByLabelText("Sleep · 23:00");
    expect(untouched).not.toHaveAttribute("aria-invalid");
    expect(untouched).toHaveAccessibleDescription(
      /Not negotiable: the floor equals the target of 8h/,
    );
  });
});

describe("the off-plan panel", () => {
  it("lists each period's span in the active zone, with its label", async () => {
    apiServer.use(...settingsHandlers({ periods: [buildOffPlanPeriod()] }));
    renderAt("/settings");
    await settled();

    const table = screen.getByRole("table", { name: /Off-plan periods/ });
    expect(table).toHaveTextContent("Barcelona");
    expect(table).toHaveTextContent("2026-08-07 \u00b7 14:00");
    expect(table).toHaveTextContent("2026-08-10 \u00b7 09:00");
  });

  it("states both meanings of keeping the frame", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Off plan");
    expect(panel).toHaveTextContent("no routine materializes inside the span either");
    expect(panel).toHaveTextContent("your routines still materialize and nothing else does");
  });

  /* The interval is named by the words the row draws, so "Times" answers for the fieldset and is written
   * once: drawn beside the control and referenced by name, not repeated as the control's own string. */
  it("names the times interval by the words the screen draws, announced once", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Off plan");
    const interval = within(panel).getByLabelText("Times");

    expect(interval.tagName).toBe("FIELDSET");
    expect(interval).not.toHaveAttribute("aria-label");
    expect(authoredNames(panel, "Times")).toEqual([
      { source: "drawn text", by: "span.form-row__label" },
    ]);

    /* The row's hint reaches the fields through the id the row hands over, so a reader gets it without
     * opening either end. */
    expect(within(panel).getByLabelText("from")).toHaveAccessibleDescription(
      expect.stringContaining("Snapped to the quarter hour"),
    );
  });

  /* An arbitrary span, not whole days: Friday afternoon to Monday morning is the case the feature exists for, and
   * the times snap to the quarter hour because every bound in this product does.
   *
   * `fireEvent.change` on the times for the reason the day-bounds case states: the kit's input snaps on blur, so a
   * typed figure would already be on the grid and this form's own snap would be untested. */
  it("declares an arbitrary span from two dates and two times, snapped to the quarter hour", async () => {
    const declare = recordingHandler("post", OFF_PLAN, {
      status: 201,
      body: buildOffPlanPeriod(),
    });
    apiServer.use(declare.handler, ...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Off plan");
    const from = within(panel).getByRole("textbox", { name: "From" });
    await userEvent.clear(from);
    await userEvent.type(from, "2026-08-07");
    const to = within(panel).getByRole("textbox", { name: "To" });
    await userEvent.clear(to);
    await userEvent.type(to, "2026-08-10");
    fireEvent.change(within(panel).getByLabelText("from"), { target: { value: "14:07" } });
    fireEvent.change(within(panel).getByLabelText("to"), { target: { value: "09:00" } });

    fireEvent.click(within(panel).getByRole("button", { name: "Declare off plan" }));

    await waitFor(() =>
      expect(declare.bodies).toEqual([
        {
          start: "2026-08-07T14:00:00+01:00",
          end: "2026-08-10T09:00:00+01:00",
          keepFrame: false,
          label: null,
        },
      ]),
    );
  });

  it("presents the frame choice at declaration and sends it", async () => {
    const declare = recordingHandler("post", OFF_PLAN, {
      status: 201,
      body: buildOffPlanPeriod({ keepFrame: true }),
    });
    apiServer.use(declare.handler, ...settingsHandlers());
    renderAt("/settings");
    await settled();

    const panel = panelNamed("Off plan");
    await userEvent.click(
      within(panel).getByRole("checkbox", { name: "Materialize routines inside the span" }),
    );
    await userEvent.click(within(panel).getByRole("button", { name: "Declare off plan" }));

    await waitFor(() => expect(declare.bodies.at(0)).toMatchObject({ keepFrame: true }));
  });

  it("edits the frame choice afterwards, on the row, without redeclaring the period", async () => {
    const edit = recordingHandler("patch", `${OFF_PLAN}/${buildOffPlanPeriod().id}`, {
      status: 200,
      body: buildOffPlanPeriod({ keepFrame: true }),
    });
    apiServer.use(edit.handler, ...settingsHandlers({ periods: [buildOffPlanPeriod()] }));
    renderAt("/settings");
    await settled();

    await userEvent.click(
      within(screen.getByRole("table", { name: /Off-plan periods/ })).getByRole("checkbox", {
        name: "nothing runs",
      }),
    );

    await waitFor(() => expect(edit.bodies).toEqual([{ keepFrame: true }]));
  });

  it("renders the 409 on an overlapping span with its stated reason", async () => {
    apiServer.use(
      recordingHandler("post", OFF_PLAN, {
        status: 409,
        body: {
          type: "syncr:conflict",
          title: "Off-plan periods overlap",
          status: 409,
          detail:
            "This span overlaps Barcelona, 2026-08-07 14:00 to 2026-08-10 09:00. Nothing was declared; " +
            "every other period still reads as it did.",
        },
      }).handler,
      ...settingsHandlers({ periods: [buildOffPlanPeriod()] }),
    );
    renderAt("/settings");
    await settled();

    await userEvent.click(screen.getByRole("button", { name: "Declare off plan" }));

    expect(await screen.findByText(/overlaps Barcelona/)).toBeInTheDocument();
  });
});

/* EVERY DEGRADATION NOTICE NAMES THE SURVIVING CAPABILITY. The type makes it impossible to build one that does not,
 * and these cases assert the words reach the reader. */
describe("the degradation panels", () => {
  it("shows the write-target expiry in oxide, at panel volume, with one reconnect action", async () => {
    apiServer.use(
      ...settingsHandlers({
        connection: buildConnection({ connected: true, notices: buildExpiryNotices() }),
        sources: [buildWriteTarget()],
      }),
    );
    renderAt("/settings");
    await settled();

    const panel = noticeAt("panel", "alert", "The plan is not reaching your calendar");
    expect(panel.className).toContain("notice--oxide");
    expect(panel).toHaveTextContent("Writes have been failing for 4 days");
    expect(panel).toHaveTextContent(
      "still works \u00b7 Reading your calendars, so the plan is still built around them",
    );
    expect(panel).toHaveTextContent("unavailable \u00b7 Writing the plan to your Google calendar");
    expect(within(panel).getAllByRole("link")).toHaveLength(1);
    expect(within(panel).getByRole("link", { name: "Reconnect Google" })).toBeInTheDocument();
  });

  /* The duration is the api's own sentence in the detail; what the panel adds is the instant the condition
   * started, rendered in the active zone, which is what completes the kit's `since` line. */
  it("states how long writes have been failing, and when they started", async () => {
    apiServer.use(
      ...settingsHandlers({
        connection: buildConnection({ connected: true, notices: buildExpiryNotices() }),
      }),
    );
    renderAt("/settings");
    await settled();

    const panel = noticeAt("panel", "alert", "The plan is not reaching your calendar");
    expect(panel).toHaveTextContent("Writes have been failing for 4 days");
    expect(panel).toHaveTextContent("since 2026-08-01 \u00b7 10:00");
  });

  /* THE NOTICE IS THE API'S OWN, arrived on the source list, and the row's sync state is deliberately FRESH: a
   * surface that computed staleness for itself would stay silent. What is asserted is that the api's words,
   * threshold sentence and all, reach the reader unchanged -- so a figure changed on the server moves this panel
   * with no edit here. */
  it("renders the api's stale-feed notice verbatim, naming a threshold this screen does not know", async () => {
    const stale = buildSource({ displayName: "Uni timetable" });
    apiServer.use(
      ...settingsHandlers({
        sources: [stale],
        sourceNotices: [
          {
            id: `calendar.feed-stale.${stale.id}`,
            volume: "panel",
            pigment: "amber",
            title: "Uni timetable could not be read",
            detail:
              "The feed answered 503 Service Unavailable. It last answered 2 days ago. A feed is reported " +
              "here once it has been failing for more than 36 hours.",
            unavailable: ["Reading new commitments from Uni timetable"],
            stillWorks: [
              "The commitments this feed already contributed, which are retained and marked possibly stale",
              "Solving the week, which still plans around every commitment already read",
            ],
            since: new Date(NOW - 48 * HOUR).toISOString(),
            action: null,
            scope: { screen: "settings", sourceId: stale.id },
          },
        ],
      }),
    );
    renderAt("/settings");
    await settled();

    const panel = noticeAt("panel", "status", "Uni timetable could not be read");
    expect(panel.className).toContain("notice--amber");
    expect(panel).toHaveTextContent("more than 36 hours");
    expect(panel).toHaveTextContent(
      "still works \u00b7 The commitments this feed already contributed",
    );
  });

  it("shows a parse rejection stating the count and the reason per class", async () => {
    apiServer.use(
      ...settingsHandlers({
        sources: [
          buildSource({
            syncState: buildSyncState({
              rejectedCount: 3,
              rejections: [
                { kind: "unknown-zone", line: 41, component: "VEVENT", detail: "TZID", uid: null },
                { kind: "unknown-zone", line: 88, component: "VEVENT", detail: "TZID", uid: null },
                {
                  kind: "missing-duration",
                  line: 120,
                  component: "VEVENT",
                  detail: "no DTEND",
                  uid: null,
                },
              ],
            }),
          }),
        ],
      }),
    );
    renderAt("/settings");
    await settled();

    const panel = screen.getByRole("status", {
      name: "3 events in Timetable could not be read",
    });
    expect(panel).toHaveTextContent("2 unknown-zone, 1 missing-duration");
    expect(panel).toHaveTextContent("still works \u00b7");
  });

  it("raises nothing at all while every source reads and nothing has expired", async () => {
    apiServer.use(...settingsHandlers());
    renderAt("/settings");
    await settled();

    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("the whole screen", () => {
  it("draws no spinner and no progress bar anywhere", async () => {
    apiServer.use(...settingsHandlers({ sources: [buildSource(), buildWriteTarget()] }));
    renderAt("/settings");
    await settled();

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(document.querySelectorAll("[class*='spinner'], [class*='skeleton']")).toHaveLength(0);
  });

  /* A refusal outranks an outstanding read, which is the reading rule one layer down: the surface a failed read
   * would feed cannot be drawn either way, and a reader waiting for a screen that will not appear learns nothing. */
  it("renders a refused read as the api's own sentence rather than as a wait", async () => {
    apiServer.use(
      jsonHandler("/api/v1/off-plan", {
        status: 503,
        body: {
          type: "syncr:dependency-unavailable",
          title: "The database is unavailable",
          status: 503,
          detail:
            "The off-plan periods could not be read. Every other setting still reads as it did.",
        },
      }),
      ...settingsHandlers(),
    );
    renderAt("/settings");
    await settled();

    expect(
      await screen.findByText(
        "The off-plan periods could not be read. Every other setting still reads as it did.",
      ),
    ).toBeInTheDocument();
  });
});
