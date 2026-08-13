/* ONE GESTURE, TWO WRITES: the whole path from an empty slot's gutter label to the requests the confirm sends.
 *
 * DRIVEN FROM THE BAND'S LABEL RATHER THAN FROM THE FORM, through the one route table the application is built
 * from. The claim this file exists for is about a reader's single act: they press the label on the week screen,
 * land in a prefilled capture, confirm once, and the api receives exactly one task and exactly one preference on
 * it. Starting at the dialog would leave the half of that path where the window is carried untested, which is
 * where a dropped value hides.
 *
 * THE PIN ROUTE IS STUBBED AND READ AT ZERO. A pin is a hard constraint on one block of the plan of record and a
 * preferred window is a cost the solver trades off, so a pin creeping onto this path would turn a soft preference
 * into something the reader never asked for. An absence read off a route nobody stubbed is not a reading, so the
 * route answers as though it would have worked and the count is taken from a handler that can fire.
 *
 * A REFUSED PREFERENCE MUST NOT LOSE THE TASK, and the reader has to be told which of the two did not land. The
 * two refusals are two different worlds and they are driven separately: a refused capture leaves the draft in a
 * form the reader can fix, and a refused preference leaves a task in the list with no window on it, which is a
 * banner in the top bar because the form has nothing left to do.
 *
 * WHAT THIS FILE CANNOT SAY. It reads the api's own answer and no further, so a request the api answered 2xx to
 * having stored nothing is indistinguishable here from one that landed. Every reading below is about a refusal
 * the api STATED. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderSignedInAt } from "../../../testing/renderRoute";
import { bannersInTheTopBar } from "../../../testing/topBar";
import { recordWrites, type WriteLog } from "../../../testing/writeLog";
import type { StubbedResponse } from "../../../testing/apiStub";
import { capturePath, preferredWindowDeclaration } from "../../../app/capture";
import {
  AREA_CAREER as WEEK_AREA,
  buildWeekView,
  installWeekReads,
  SLOT_LABEL,
  WEEK_PATH,
} from "../../week/__tests__/fixtures";
import { AREA_CAREER, buildBacklog, buildProblem, buildSettings } from "./fixtures";
import { stubBacklog } from "./render";

const CAPTURE = "Capture a task";
const NOT_SAVED = "A task you captured was not saved";
const WINDOW_NOT_SAVED = "A task was saved without the time you captured it from";
const THE_WINDOW_SENTENCE = /slot you activated/i;

const CAPTURE_PATH = "/api/v1/tasks";
const PREFERENCE_PATH = "/api/v1/tasks/:taskId/preference";
const PINS_PATH = "/api/v1/weeks/:isoWeek/pins";

/* The identifier the api mints for the captured task, which is the only place the second request's address can
   come from: it is in no URL the reader visited and in no request body. */
const MINTED_TASK = "b41d9e70-77c5-4a6e-9a0f-2c7e5d8b1f34";

/* The slot the week fixture draws: an hour on the Wednesday, charged to Career, which the reader's own zone reads
   as 14:00 to 15:00. The declaration drops the dates, because a preference is a time of day. */
const SLOT_FROM = "2026-02-11T14:00:00+00:00";
const SLOT_TO = "2026-02-11T15:00:00+00:00";
const SLOT_START = "14:00";
const SLOT_END = "15:00";
const SLOT_MINUTES = 60;
const THE_TITLE = "Kontron take-home";

const CAPTURED: StubbedResponse = { status: 201, body: { id: MINTED_TASK } };
const DECLARED: StubbedResponse = {
  status: 200,
  body: { owner: {}, declared: {}, effective: {} },
};

const PREFERENCE_REFUSED: StubbedResponse = {
  status: 422,
  body: buildProblem({ detail: "A window has to land on the quarter hour." }),
};

const CAPTURE_REFUSED: StubbedResponse = {
  status: 422,
  body: buildProblem({ detail: "The estimate has to be at least as long as the minimum chunk." }),
};

/** The three write paths of the gesture, installed over the screen's own read stubs so they answer first. */
function stubTheWrites(capture: StubbedResponse, preference: StubbedResponse): WriteLog {
  return recordWrites([
    { method: "post", path: CAPTURE_PATH, answer: capture },
    { method: "put", path: PREFERENCE_PATH, answer: preference },
    { method: "post", path: PINS_PATH, answer: { status: 201, body: {} } },
  ]);
}

/**
 * The reader's whole gesture: the week screen, the slot's own label, the title, and one confirm.
 *
 * The Area and the estimate are the prefill's, so nothing is chosen here: a case that picked an Area would be
 * driving a form rather than the path a slot's label opens.
 */
async function captureFromTheSlot(): Promise<void> {
  await userEvent.click(await screen.findByRole("button", { name: SLOT_LABEL }));
  const dialog = await screen.findByRole("dialog", { name: CAPTURE });
  await userEvent.type(within(dialog).getByRole("textbox", { name: /Task/ }), THE_TITLE);
  await userEvent.click(within(dialog).getByRole("button", { name: "Capture" }));
}

/** The week screen, its reads, and the backlog the reader lands on. */
async function onTheWeekScreen(): Promise<void> {
  stubBacklog({ backlog: buildBacklog() });
  installWeekReads(buildWeekView());
  await renderSignedInAt(WEEK_PATH);
}

describe("one confirm from a slot's prefilled capture", () => {
  it("sends the task, then its preference, and no pin", async () => {
    await onTheWeekScreen();
    const log = stubTheWrites(CAPTURED, DECLARED);

    await captureFromTheSlot();

    await waitFor(() => {
      expect(log.sequence()).toEqual([`POST ${CAPTURE_PATH}`, `PUT ${PREFERENCE_PATH}`]);
    });
    expect(log.countOf("post", PINS_PATH)).toBe(0);
  });

  /* THE TWO BODIES WHOLE. The capture carries no preference member, because the request shape refuses one, and the
     preference carries the slot's own window at soft: asserting the members one at a time would let a member
     nobody decided ride along in either. */
  it("carries the slot's Area and length in the capture, and the slot's window at soft in the preference", async () => {
    await onTheWeekScreen();
    const log = stubTheWrites(CAPTURED, DECLARED);

    await captureFromTheSlot();

    await waitFor(() => {
      expect(log.wrote).toHaveLength(2);
    });
    expect(log.wrote.at(0)).toEqual({
      method: "post",
      pattern: CAPTURE_PATH,
      path: CAPTURE_PATH,
      body: {
        areaId: WEEK_AREA,
        title: THE_TITLE,
        estimateMinutes: SLOT_MINUTES,
        minChunkMinutes: 15,
        deadline: null,
        priority: "normal",
        splittable: true,
      },
    });
    expect(log.wrote.at(1)).toEqual({
      method: "put",
      pattern: PREFERENCE_PATH,
      path: `/api/v1/tasks/${MINTED_TASK}/preference`,
      body: {
        windows: [{ start: SLOT_START, end: SLOT_END }],
        strength: "soft",
        preferredDurationMinutes: null,
      },
    });
  });

  it("closes the form and says nothing was refused", async () => {
    await onTheWeekScreen();
    stubTheWrites(CAPTURED, DECLARED);

    await captureFromTheSlot();

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: CAPTURE })).toBeNull();
    });
    expect(bannersInTheTopBar()).toEqual([]);
  });

  /* THE FORM CLAIMS THE WRITE, so the sentence has to stay true once the write exists. Before this gesture wrote
     anything it stated a fact about the slot; a task whose own preference the confirm declares does not inherit
     its Area's, so the inheritance sentence is not the one this opening gets. */
  it("says the confirm will prefer that stretch for this task alone, and not that it is inherited", async () => {
    await onTheWeekScreen();
    stubTheWrites(CAPTURED, DECLARED);

    await userEvent.click(await screen.findByRole("button", { name: SLOT_LABEL }));
    const dialog = await screen.findByRole("dialog", { name: CAPTURE });

    expect(within(dialog).getByText(THE_WINDOW_SENTENCE)).toHaveTextContent(
      "The slot you activated runs 2026-02-11 14:00 to 2026-02-11 15:00, and capturing this " +
        "prefers that stretch for this task alone: a soft preference of its own, in place of its Area's.",
    );
    expect(within(dialog).queryByText(/inherited from the Area/)).toBeNull();
  });
});

describe("a preference the api refuses", () => {
  /* THE TASK IS NOT LOST, AND THAT IS THE FIRST THING THE READER IS TOLD. The capture landed, so the form has
     nothing left to fix and sending the draft again would capture the task twice. */
  it("keeps the task, closes the form, and names the preferred time as the write that did not land", async () => {
    await onTheWeekScreen();
    const log = stubTheWrites(CAPTURED, PREFERENCE_REFUSED);

    await captureFromTheSlot();

    const banner = await screen.findByRole("alert", { name: WINDOW_NOT_SAVED });
    expect(bannersInTheTopBar()).toEqual([banner]);
    expect(banner).toHaveClass("notice--banner", "notice--oxide");
    expect(banner.textContent).toContain("The task itself was saved.");
    expect(banner.textContent).toContain("A window has to land on the quarter hour.");
    expect(banner.textContent).toContain(
      "still works · the task, which is in your backlog, the next plan, which will place it " +
        "without a preferred time",
    );
    expect(log.countOf("post", CAPTURE_PATH)).toBe(1);
    expect(screen.queryByRole("dialog", { name: CAPTURE })).toBeNull();
  });

  /* THE TWO SENTENCES ARE NOT INTERCHANGEABLE. The capture's own banner says the title the reader typed is gone
     and the backlog is unchanged; both are false here, and reading a task that was saved as one that was not is
     the failure this case exists to catch. */
  it("does not say the task was not saved, because it was", async () => {
    await onTheWeekScreen();
    stubTheWrites(CAPTURED, PREFERENCE_REFUSED);

    await captureFromTheSlot();

    await screen.findByRole("alert", { name: WINDOW_NOT_SAVED });
    expect(screen.queryByRole("alert", { name: NOT_SAVED })).toBeNull();
    expect(bannersInTheTopBar().at(0)?.textContent).not.toContain("was not saved either");
  });
});

describe("a capture the api refuses", () => {
  /* NOTHING WAS CREATED, so there is nothing to declare a preference on: sending one would address a task that
     does not exist. The draft is what the reader has left and the refusal belongs at the rows it names. */
  it("declares no preference, keeps the draft, and states the refusal in the form", async () => {
    await onTheWeekScreen();
    const log = stubTheWrites(CAPTURE_REFUSED, DECLARED);

    await captureFromTheSlot();

    const dialog = await screen.findByRole("dialog", { name: CAPTURE });
    await waitFor(() => {
      expect(
        within(dialog).getByText(/The estimate has to be at least as long as the minimum chunk/),
      ).toBeInTheDocument();
    });
    expect(log.sequence()).toEqual([`POST ${CAPTURE_PATH}`]);
    expect(within(dialog).getByRole("textbox", { name: /Task/ })).toHaveValue(THE_TITLE);
    expect(bannersInTheTopBar()).toEqual([]);
  });
});

describe("the n binding, which carries no window", () => {
  it("sends one capture and declares no preference", async () => {
    stubBacklog({ backlog: buildBacklog() });
    await renderSignedInAt("/areas");
    const log = stubTheWrites(CAPTURED, DECLARED);

    await userEvent.keyboard("n");
    const dialog = await screen.findByRole("dialog", { name: CAPTURE });
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Task/ }), THE_TITLE);
    await userEvent.click(within(dialog).getByRole("combobox", { name: /Area/ }));
    await userEvent.click(screen.getByRole("option", { name: "Career" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(log.sequence()).toEqual([`POST ${CAPTURE_PATH}`]);
    });
    expect(log.countOf("post", PINS_PATH)).toBe(0);
  });
});

describe("the window a preference declares", () => {
  /* TWO CLOCK TIMES, NOT TWO INSTANTS, because a preference is a time of day: the api resolves the pair against
     whatever zone is in force on each date it reads the window for. */
  it("is both ends on the reader's own wall clock", () => {
    expect(preferredWindowDeclaration({ from: SLOT_FROM, to: SLOT_TO }, "Europe/London")).toEqual({
      start: SLOT_START,
      end: SLOT_END,
    });
  });

  it("reads the same two instants as the zone the reader is in, not as UTC", () => {
    expect(preferredWindowDeclaration({ from: SLOT_FROM, to: SLOT_TO }, "Europe/Madrid")).toEqual({
      start: "15:00",
      end: "16:00",
    });
  });

  /* AN END AT MIDNIGHT IS `00:00`, which the api reads as the END of the day: it is the one bound it lets read
     earlier than the start it belongs to, because a `time` cannot spell 24:00. Nothing here special-cases it. */
  it("declares a slot that runs to midnight as ending at 00:00", () => {
    expect(
      preferredWindowDeclaration(
        { from: "2026-02-11T23:00:00+00:00", to: "2026-02-12T00:00:00+00:00" },
        "Europe/London",
      ),
    ).toEqual({ start: "23:00", end: "00:00" });
  });

  /* A STRETCH THAT WRAPS PAST MIDNIGHT IS SENT AS THE TWO TIMES IT IS, and the api stores it as the two windows it
     splits into. Splitting it here would be a second implementation of a rule the domain already owns, and the two
     would disagree the first time either moved. */
  it("sends a stretch across midnight as the pair it is, leaving the split to the api", () => {
    expect(
      preferredWindowDeclaration(
        { from: "2026-02-11T23:30:00+00:00", to: "2026-02-12T00:30:00+00:00" },
        "Europe/London",
      ),
    ).toEqual({ start: "23:30", end: "00:30" });
  });

  /* NOTHING TO SEND RATHER THAN A PAIR OF FAILURES, and it is the same absence the form's own sentence answers
     with: a window the reader was never shown is not one their confirm declares. */
  it("declares nothing where the zone or an instant cannot be read", () => {
    expect(preferredWindowDeclaration({ from: SLOT_FROM, to: SLOT_TO }, "Mars/Olympus")).toBeNull();
    expect(preferredWindowDeclaration({ from: "soon", to: SLOT_TO }, "Europe/London")).toBeNull();
  });

  /* THE ZONE THROUGH THE WHOLE PATH. A reader in Madrid activated the slot their own week screen drew at 15:00, and
     what the api is sent has to be the clock they read: a declaration composed in UTC would put the work an hour
     off for every reader east of London, with every case above still green. */
  it("reaches the api in the reader's own zone, driven from the URL a slot writes", async () => {
    stubBacklog({
      backlog: buildBacklog(),
      settings: buildSettings({ homeZone: "Europe/Madrid" }),
    });
    await renderSignedInAt(
      capturePath({
        areaId: AREA_CAREER,
        estimateMinutes: SLOT_MINUTES,
        preferredWindow: { from: SLOT_FROM, to: SLOT_TO },
      }),
    );
    const log = stubTheWrites(CAPTURED, DECLARED);

    const dialog = await screen.findByRole("dialog", { name: CAPTURE });
    await userEvent.type(within(dialog).getByRole("textbox", { name: /Task/ }), THE_TITLE);
    await userEvent.click(within(dialog).getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(log.wrote).toHaveLength(2);
    });
    expect(log.wrote.at(1)?.body).toEqual({
      windows: [{ start: "15:00", end: "16:00" }],
      strength: "soft",
      preferredDurationMinutes: null,
    });
  });
});
