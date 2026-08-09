/* The four outcome controls, the keys that reach them, and what each one sends.
 *
 * EVERY PATH HERE IS DRIVEN WITHOUT A POINTER WHERE THE CLAIM IS THE KEYBOARD. `user.tab()` and
 * `user.keyboard()` are the whole of it: a test that clicked a control and then asserted the keystroke would
 * be asserting the click.
 *
 * THE OPTIMISTIC FRAME IS ASSERTED ON THE ROW, not on the cache. What the reader gets for one action is the
 * row reading differently before the response lands, and the response here is held until the assertion has
 * been made. */

import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { readyz } from "../../../testing/apiStub";
import { renderSignedInAt } from "../../../testing/renderRoute";
import type { Problem } from "../../../contract";
import { clockIn } from "../instants";
import { isoWeekOf } from "../isoWeek";
import {
  BLOCK_GYM,
  ZONE,
  buildAreas,
  buildBackfill,
  buildDay,
  buildEmptyDay,
  buildGymRow,
  buildOutcome,
  buildOutcomeRejection,
} from "./fixtures";
import { heldResponse, hostToday, onHostToday, renderToday } from "./render";

const origin = window.location.origin;
const OUTCOME = `${origin}/api/v1/blocks/:blockId/outcome`;
const CONFIRM = `${origin}/api/v1/days/:date/confirm`;
const RANGE = `${origin}/api/v1/days/confirm-range`;
const PINS = `${origin}/api/v1/weeks/:isoWeek/pins`;

interface Sent {
  readonly bodies: unknown[];
  readonly paths: string[];
}

/** Records every outcome the screen records, and answers with what the test gave it. */
function stubRecording(status = 200, body: Problem | null = null): Sent {
  const bodies: unknown[] = [];
  const paths: string[] = [];
  apiServer.use(
    http.put(OUTCOME, async ({ request, params }) => {
      bodies.push(await request.json());
      paths.push(String(params.blockId));
      return HttpResponse.json(body, { status });
    }),
  );
  return { bodies, paths };
}

/** A pin route that fails the test if the screen ever reaches it: a `moved` outcome creates no pin. */
function stubPins(): { readonly calls: number } {
  const seen = { calls: 0 };
  apiServer.use(
    http.post(PINS, () => {
      seen.calls += 1;
      return HttpResponse.json(null);
    }),
  );
  return seen;
}

/** The row whose title is `title`, so a test asserts on one row rather than on the screen. */
async function rowOf(title: string): Promise<HTMLElement> {
  const cell = await screen.findByText(title);
  return cell.closest(".ledger__row") as HTMLElement;
}

/** Focus the row's own controls without a pointer, which is how a bare keystroke finds its row. */
async function focusRow(title: string): Promise<HTMLElement> {
  const row = await rowOf(title);
  const user = userEvent.setup();
  within(row).getByRole("button", { name: /skip/ }).focus();
  /* Tabbing once from the skip control keeps focus inside the same row, which is the state the keys read. */
  await user.tab();
  return row;
}

/**
 * How many times a control named `label` entered the document while `act` ran.
 *
 * A keystroke that both navigates and opens a form produces one commit: React batches the router's state
 * update with the form's, so the form is unmounted with the screen it belonged to and was never in the DOM to
 * query for. A query made after `act` therefore reads the same empty document whether the keystroke reached
 * that form or not. The observer's records hold the nodes themselves, so an opening that survived no commit
 * is still countable.
 */
async function appearancesWhile(label: string, act: () => Promise<void>): Promise<number> {
  let seen = 0;
  const count = (records: readonly MutationRecord[]): void => {
    for (const record of records) {
      for (const node of record.addedNodes) {
        if (node instanceof HTMLElement)
          seen += node.querySelectorAll(`[aria-label="${label}"]`).length;
      }
    }
  };
  const observer = new MutationObserver(count);
  observer.observe(document.body, { subtree: true, childList: true });
  await act();
  count(observer.takeRecords());
  observer.disconnect();
  return seen;
}

const GYM = "Gym \u00B7 Chest & Back";

describe("skipping a row", () => {
  it("records a skip with the week the ledger's date belongs to", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    const row = await rowOf(GYM);

    await userEvent.setup().click(within(row).getByRole("button", { name: /skip/ }));

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    expect(sent.bodies[0]).toEqual({ isoWeek: isoWeekOf(hostToday()), state: "skipped" });
    expect(sent.paths).toEqual([BLOCK_GYM]);
  });

  it("reads as skipped before the api answers", async () => {
    const stub = await renderToday(onHostToday(buildDay()));
    const { held, release } = heldResponse();
    apiServer.use(
      http.put(OUTCOME, async () => {
        await held;
        return HttpResponse.json(null);
      }),
    );
    const row = await rowOf(GYM);

    await userEvent.setup().click(within(row).getByRole("button", { name: /skip/ }));

    expect(await within(await rowOf(GYM)).findByText("skipped")).toBeInTheDocument();

    /* Released and settled here, so the invalidation that follows a recording is asserted rather than left
       running past the end of the test. */
    release();
    await waitFor(() => expect(stub.reads()).toBe(2));
  });

  /* `x` on the focused row, reached by tabbing. No pointer touches this path. */
  it("skips the focused row on x, without a pointer", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);

    await userEvent.setup().keyboard("x");

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    expect(sent.paths).toEqual([BLOCK_GYM]);
  });

  /* The rule the module's own header states, and the path that actually breaks it: focus ENTERED a row and
     then left it. A test that never focused anything passes whether or not the row is ever released, so it
     defends nothing. */
  it("does nothing on x once focus has left the row it was on", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    screen.getByRole("button", { name: /Confirm the day/ }).focus();
    await user.keyboard("x");

    expect(sent.bodies).toEqual([]);
  });

  it("does nothing on x once focus has left the ledger entirely", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    const row = await focusRow(GYM);
    const user = userEvent.setup();

    (document.activeElement as HTMLElement).blur();
    await user.keyboard("x");

    expect(sent.bodies).toEqual([]);
    expect(within(row).getByText("presumed")).toBeInTheDocument();
  });

  /* The counterpart, so the release cannot be implemented by never claiming a row at all: focus moving from
     one control of a row to another releases and reclaims it in one turn, and the row a key acts on is the
     one it ends on. */
  it("keeps the row while focus moves between its own controls", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    const row = await rowOf(GYM);
    const user = userEvent.setup();

    within(row).getByRole("button", { name: /skip/ }).focus();
    await user.tab();
    await user.tab();
    await user.keyboard("x");

    await waitFor(() => expect(sent.paths).toEqual([BLOCK_GYM]));
  });

  it("does nothing on x while no row has ever been focused", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await screen.findByText(GYM);

    await userEvent.setup().keyboard("x");

    expect(sent.bodies).toEqual([]);
  });

  it("offers the way back to presumed only on a row that has been answered for", async () => {
    await renderToday(
      onHostToday(
        buildDay({
          behind: [buildGymRow({ outcome: buildOutcome({ state: "skipped" }) })],
          ahead: [],
          blockCount: 1,
          presumedCount: 0,
        }),
      ),
    );
    const sent = stubRecording();
    const row = await rowOf(GYM);

    await userEvent.setup().click(within(row).getByRole("button", { name: "presumed" }));

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    expect(sent.bodies[0]).toEqual({ isoWeek: isoWeekOf(hostToday()), state: "presumed" });
  });

  it("offers no way back on a row nobody has said anything about", async () => {
    await renderToday(onHostToday(buildDay()));
    const row = await rowOf(GYM);

    expect(within(row).queryByRole("button", { name: "presumed" })).not.toBeInTheDocument();
  });
});

describe("the minutes a block really took", () => {
  it("opens on Shift+X prefilled with the planned duration, stepping by five", async () => {
    await renderToday(onHostToday(buildDay()));
    await focusRow(GYM);

    await userEvent.setup().keyboard("{Shift>}X{/Shift}");

    const field = await screen.findByLabelText(`actual minutes for ${GYM}`);
    expect(field).toHaveValue(60);
    expect(field).toHaveAttribute("step", "5");
    /* No floor on the control: a number field takes `min` as the step BASE, so a floor of 1 would put the
       browser's own arrow keys on 1, 6, 11 and step 420 to 416. The floor is stated beside the control and
       applied to what is sent. */
    expect(field).not.toHaveAttribute("min");
    expect(screen.getByText("min of 60m planned")).toBeInTheDocument();
  });

  /* The keystroke that asks for a figure has to leave the reader on the field that holds it. The control that
     opened the form unmounted with it, so without the handoff focus falls to the document and the value can
     be entered only with a pointer. */
  it("puts focus on the field it just opened", async () => {
    await renderToday(onHostToday(buildDay()));
    await focusRow(GYM);

    await userEvent.setup().keyboard("{Shift>}X{/Shift}");

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText(`actual minutes for ${GYM}`)),
    );
  });

  /* Enter in the field is the browser's own submit rather than a keystroke this screen interprets, so
     `Shift+X` then Enter records the planned duration as a partial. Stepping the figure with the arrow keys
     is the browser's own too, and jsdom does not implement it: the arrow path is asserted in Chrome, and the
     stepper's own buttons cover the step here. */
  it("records what the field holds when Enter is pressed in it", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByLabelText(`actual minutes for ${GYM}`)),
    );
    await user.keyboard("{Enter}");

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    expect(sent.bodies[0]).toEqual({
      isoWeek: isoWeekOf(hostToday()),
      state: "partial",
      actualMinutes: 60,
    });
  });

  it("gives focus back to the row when the form closes", async () => {
    await renderToday(onHostToday(buildDay()));
    const row = await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    await user.click(await screen.findByRole("button", { name: "cancel" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(within(row).getByRole("button", { name: /skip/ })),
    );
  });

  /* The common case in two keystrokes: open the stepper, step down once, record. */
  it("records the figure the stepper holds", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    await user.click(screen.getByRole("button", { name: "decrease 5 minutes" }));
    await user.click(screen.getByRole("button", { name: "record partial" }));

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    expect(sent.bodies[0]).toEqual({
      isoWeek: isoWeekOf(hostToday()),
      state: "partial",
      actualMinutes: 55,
    });
  });

  it("shows the minutes on the row as soon as they are recorded", async () => {
    const stub = await renderToday(onHostToday(buildDay()));
    const { held, release } = heldResponse();
    apiServer.use(
      http.put(OUTCOME, async () => {
        await held;
        return HttpResponse.json(null);
      }),
    );
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    await user.click(screen.getByRole("button", { name: "record partial" }));

    expect(
      await within(await rowOf(GYM)).findByText("partial \u00B7 60m of 60m planned"),
    ).toBeInTheDocument();

    release();
    await waitFor(() => expect(stub.reads()).toBe(2));
  });

  it("refuses to record a figure the api would reject, and says what the bound is", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    fireEvent.change(await screen.findByLabelText(`actual minutes for ${GYM}`), {
      target: { value: "0" },
    });

    expect(screen.getByRole("button", { name: "record partial" })).toBeDisabled();
    expect(screen.getByText("1 to 1440 minutes")).toBeInTheDocument();
    expect(sent.bodies).toEqual([]);
  });

  it("closes without sending when the reader cancels", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("{Shift>}X{/Shift}");
    await user.click(await screen.findByRole("button", { name: "cancel" }));

    expect(screen.queryByLabelText(`actual minutes for ${GYM}`)).not.toBeInTheDocument();
    expect(sent.bodies).toEqual([]);
    expect(within(await rowOf(GYM)).getByRole("button", { name: /skip/ })).toBeInTheDocument();
  });
});

describe("the interval a block really ran in", () => {
  it("opens on m prefilled with the planned interval, on the field the reader types into", async () => {
    await renderToday(onHostToday(buildDay()));
    await focusRow(GYM);

    await userEvent.setup().keyboard("m");

    const start = await screen.findByLabelText(`when ${GYM} really happened, from`);
    expect(start).toHaveValue("07:00");
    expect(screen.getByLabelText(`when ${GYM} really happened, to`)).toHaveValue("08:00");
    await waitFor(() => expect(document.activeElement).toBe(start));
  });

  it("records the interval as instants in the day's own zone, and creates no pin", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    const pins = stubPins();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("m");
    fireEvent.change(await screen.findByLabelText(`when ${GYM} really happened, from`), {
      target: { value: "09:00" },
    });
    fireEvent.change(screen.getByLabelText(`when ${GYM} really happened, to`), {
      target: { value: "10:15" },
    });
    await user.click(screen.getByRole("button", { name: "record moved" }));

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    const body = sent.bodies[0] as {
      isoWeek: string;
      state: string;
      actualInterval: { start: string; end: string };
    };
    expect(body.state).toBe("moved");
    expect(body.isoWeek).toBe(isoWeekOf(hostToday()));
    expect(clockIn(body.actualInterval.start, ZONE)).toBe("09:00");
    expect(clockIn(body.actualInterval.end, ZONE)).toBe("10:15");
    expect(pins.calls).toBe(0);
  });

  /* An end at or before the start ran into the following day, which is what a block crossing midnight
     does. The span the api will bound is then a real interval rather than a reversed one. */
  it("puts an end at or before the start on the following day", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("m");
    fireEvent.change(await screen.findByLabelText(`when ${GYM} really happened, from`), {
      target: { value: "23:00" },
    });
    fireEvent.change(screen.getByLabelText(`when ${GYM} really happened, to`), {
      target: { value: "06:00" },
    });
    await user.click(screen.getByRole("button", { name: "record moved" }));

    await waitFor(() => expect(sent.bodies).toHaveLength(1));
    const { actualInterval } = sent.bodies[0] as {
      actualInterval: { start: string; end: string };
    };
    expect(Date.parse(actualInterval.end) - Date.parse(actualInterval.start)).toBe(
      7 * 60 * 60 * 1000,
    );
  });

  it("refuses to record an interval with an end the reader cleared", async () => {
    await renderToday(onHostToday(buildDay()));
    const sent = stubRecording();
    await focusRow(GYM);
    const user = userEvent.setup();

    await user.keyboard("m");
    fireEvent.change(await screen.findByLabelText(`when ${GYM} really happened, to`), {
      target: { value: "" },
    });

    expect(screen.getByRole("button", { name: "record moved" })).toBeDisabled();
    expect(screen.getByText(/both ends need a time/)).toBeInTheDocument();
    expect(sent.bodies).toEqual([]);
  });

  /* A CHORD IS ONE GESTURE, and `m` is the case where that is hardest to see: it names a screen, so the chord
     both navigates and would feed this row's own binding, and the navigation unmounts the form that binding
     opens. `g m` navigated AND opened the moved control on the focused row before the shell consumed the
     keystroke. */
  it("does nothing on g m beyond navigating, because the chord consumed the keystroke", async () => {
    await renderToday(onHostToday(buildDay()));
    await focusRow(GYM);
    const user = userEvent.setup();

    const openings = await appearancesWhile(`when ${GYM} really happened, from`, () =>
      user.keyboard("gm"),
    );

    expect(openings).toBe(0);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Templates");
  });

  /* The zero above is evidence only if the same reading can be non-zero, so it is taken again over the
     keystroke that really does open the form. Without this, a reading that could see nothing at all would
     report the rule holding. */
  it("counts the moved control opening on a bare m", async () => {
    await renderToday(onHostToday(buildDay()));
    await focusRow(GYM);
    const user = userEvent.setup();

    const openings = await appearancesWhile(`when ${GYM} really happened, from`, () =>
      user.keyboard("m"),
    );

    expect(openings).toBe(1);
  });
});

describe("a refused recording", () => {
  it("puts the row back and states the refusal beside it", async () => {
    await renderToday(onHostToday(buildDay()));
    stubRecording(422, buildOutcomeRejection());
    const row = await rowOf(GYM);

    await userEvent.setup().click(within(row).getByRole("button", { name: /skip/ }));

    const notice = await screen.findByRole("status", { name: "Validation failed" });
    expect(notice).toHaveClass("notice--inline");
    expect(notice).toHaveClass("notice--amber");
    expect(notice).toHaveTextContent("state requires actualMinutes.");
    expect(notice).toHaveTextContent("still works \u00B7 this row, which still reads as it did");
    expect(within(await rowOf(GYM)).getByText("presumed")).toBeInTheDocument();
  });
});

describe("confirming the day", () => {
  /* `c` applies the rule its own button applies. Confirming a day with no block stores nothing, and
     confirming a day the screen has not read cannot know what it is answering for; both bump the solve-input
     version of this week and every later one, so neither is a no-op on the server. */
  it("does nothing on c while the day holds no block, which is when the control is disabled", async () => {
    await renderToday(onHostToday(buildEmptyDay()));
    const dates: string[] = [];
    apiServer.use(
      http.post(CONFIRM, ({ params }) => {
        dates.push(String(params.date));
        return HttpResponse.json(buildEmptyDay());
      }),
    );
    await screen.findByText("No blocks are planned for this day");

    await userEvent.setup().keyboard("c");

    expect(dates).toEqual([]);
    expect(screen.getByRole("button", { name: /Confirm the day/ })).toBeDisabled();
  });

  it("does nothing on c while the ledger has not arrived", async () => {
    const dates: string[] = [];
    apiServer.use(
      readyz(),
      http.get(`${origin}/api/v1/areas`, () => HttpResponse.json(buildAreas())),
      http.get(`${origin}/api/v1/days/:date`, () => new Promise<never>(() => {})),
      http.post(CONFIRM, ({ params }) => {
        dates.push(String(params.date));
        return HttpResponse.json(buildDay());
      }),
    );
    await renderSignedInAt("/today");
    await screen.findByText("Reading today");

    await userEvent.setup().keyboard("c");

    expect(dates).toEqual([]);
  });

  /* A CHORD IS ONE GESTURE. `c` names no screen, so `g c` resolves the chord to nothing and must reach no
     binding: the shell consumes that keystroke. Before it did, `g c` confirmed the day, which bumps the
     solve-input version of this week and every later one. */
  it("does nothing on g c, because the chord consumed the keystroke", async () => {
    await renderToday(onHostToday(buildDay()));
    const dates: string[] = [];
    apiServer.use(
      http.post(CONFIRM, ({ params }) => {
        dates.push(String(params.date));
        return HttpResponse.json(buildDay());
      }),
    );
    await screen.findByText(GYM);

    await userEvent.setup().keyboard("gc");

    expect(dates).toEqual([]);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Today");
  });

  it("confirms on c, and every row reads as recorded before the api answers", async () => {
    const stub = await renderToday(onHostToday(buildDay()));
    const { held, release } = heldResponse();
    const dates: string[] = [];
    apiServer.use(
      http.post(CONFIRM, async ({ params }) => {
        dates.push(String(params.date));
        await held;
        return HttpResponse.json(buildDay());
      }),
    );
    await screen.findByText(GYM);

    await userEvent.setup().keyboard("c");

    await waitFor(() => expect(dates).toEqual([hostToday()]));
    expect(await screen.findAllByText("recorded")).toHaveLength(4);
    expect(screen.queryByText("This day is not confirmed")).not.toBeInTheDocument();

    release();
    await waitFor(() => expect(stub.reads()).toBe(2));
  });

  it("puts the day back and states the refusal on the day", async () => {
    await renderToday(onHostToday(buildDay()));
    apiServer.use(
      http.post(CONFIRM, () =>
        HttpResponse.json(buildOutcomeRejection({ detail: "That day has not begun yet." }), {
          status: 422,
        }),
      ),
    );
    await screen.findByText(GYM);

    await userEvent.setup().click(screen.getByRole("button", { name: /Confirm the day/ }));

    const notice = await screen.findByRole("status", { name: "Validation failed" });
    expect(notice).toHaveTextContent("That day has not begun yet.");
    expect(notice).toHaveTextContent("still works \u00B7 the ledger, which still reads as it did");
    expect(screen.getByText("This day is not confirmed")).toBeInTheDocument();
    expect(screen.getAllByText("presumed")).toHaveLength(2);
  });
});

describe("backfilling the days before this one", () => {
  it("confirms the days the count was taken over, and states what it settled", async () => {
    const stub = await renderToday(onHostToday(buildDay({ unconfirmedDays: 3 })));
    const bodies: unknown[] = [];
    apiServer.use(
      http.post(RANGE, async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json(buildBackfill({ confirmedDays: 3, blocksRecorded: 41 }));
      }),
    );

    await userEvent.setup().click(await screen.findByRole("button", { name: "Backfill 3 days" }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    const range = bodies[0] as { from: string; to: string };
    const days = (Date.parse(range.to) - Date.parse(range.from)) / (24 * 60 * 60 * 1000) + 1;
    expect(days).toBe(28);
    expect(Date.parse(range.to)).toBeLessThan(Date.parse(hostToday()));

    const notice = await screen.findByRole("status", { name: "Past days confirmed" });
    expect(notice).toHaveClass("notice--verdigris");
    expect(notice).toHaveTextContent("3 days confirmed, 41 blocks recorded.");
    /* The day is read again, because its own count of unconfirmed days has changed. */
    await waitFor(() => expect(stub.reads()).toBe(2));
  });
});
