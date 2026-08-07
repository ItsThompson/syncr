/* THE PIN INTERACTION, END TO END, THROUGH THE REAL ROUTE AND THE REAL CLIENT.
 *
 * WHAT THESE ANSWER THAT A COMPONENT TEST CANNOT is whether the request the client BUILDS matches the route the api
 * declares, what it carries, and what it does NOT send: three of the rules here are about a request that must not
 * exist, and only a network double can say that.
 *
 * THE GEOMETRY IS STUBBED AND THE ARITHMETIC IS NOT. jsdom lays nothing out, so the canvas is given a box; what turns
 * a pointer position into a quarter hour and a quarter hour into an instant is the shipped code. The two figures a
 * reader should check: the reference grid is 626px over twelve visible hours, so a minute is 0.86944px, and the
 * fixture's axis starts at 06:00, so 365px below the canvas top is 13:00.
 *
 * A PIN IS A TRAINING LABEL, which is why the no-request cases matter as much as the request. A pin created by a
 * jittery pointer is a false preference the learning layer would fit against, and a pin created by a mistyped chord is
 * a hard constraint the solver then honours. */

import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { renderAt } from "../../../testing/renderRoute";
import { GRID_H_PX, travelFloorPx } from "../../../ui/domain";
import {
  APPLICATION,
  BLOCK_APPLICATION,
  BLOCK_LEETCODE,
  ISO_WEEK,
  LEETCODE,
  WEEK_PATH,
  buildBlock,
  buildOperation,
  buildPin,
  buildPinned,
  buildPlan,
  buildVerdict,
  buildWeekView,
  installWeekReads,
  monday,
} from "./fixtures";
import type { components } from "../../../api/schema";

type Pinned = components["schemas"]["PinnedResponse"];

const PINS = `${window.location.origin}/api/v1/weeks/${ISO_WEEK}/pins`;

/** The axis the fixture yields: 06:00 to 22:00, so 360 minutes in and 960 minutes wide. */
const AXIS_START_MIN = 360;
const VISIBLE_HOURS = 12;
const PX_PER_MIN = GRID_H_PX / (VISIBLE_HOURS * 60);

/** An ordinary trackpad click's movement, which must never state a placement. */
const SLOP_PX = 3;

/* WHAT A NO-REQUEST ASSERTION HAS TO WAIT FOR. A write is a round trip, so reading the recorder in the same tick as
 * the release passes whether or not the request was made: the first version of the sweep below did exactly that and
 * stayed green with the travel floor deleted. There is no condition to wait ON for something that must not happen, so
 * the wait is a settle, the same shape `useOperation.test.tsx` uses for the same reason. */
const SETTLE_MS = 60;
const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, SETTLE_MS));

/** Where in the canvas a wall-clock minute of the fixture's own day falls. */
function offsetOf(minutes: number): number {
  return (minutes - AXIS_START_MIN) * PX_PER_MIN;
}

/* THE CANVAS IS GIVEN A BOX AND NOTHING ELSE IS. `getBoundingClientRect` answers zeros in jsdom, which would make
 * every pointer position land on the axis start: the drag would still "work" and would prove nothing about the
 * arithmetic. Only the canvas is measured, because that is the one element the drag reads. */
let restoreRect: (() => void) | null = null;

beforeEach(() => {
  const original = Element.prototype.getBoundingClientRect;
  Element.prototype.getBoundingClientRect = function measured(this: Element): DOMRect {
    if (!this.classList.contains("week-day__canvas")) return original.call(this);
    const height = 960 * PX_PER_MIN;
    return {
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 137,
      bottom: height,
      width: 137,
      height,
      toJSON: () => ({}),
    } as DOMRect;
  };
  restoreRect = () => {
    Element.prototype.getBoundingClientRect = original;
  };
});

afterEach(() => {
  restoreRect?.();
  restoreRect = null;
});

interface PinRecording {
  readonly bodies: unknown[];
  readonly keys: (string | null)[];
}

/** The pin route, recording what it was sent and the idempotency key it was sent with. */
function recordPins(answer: Pinned = buildPinned()): PinRecording {
  const bodies: unknown[] = [];
  const keys: (string | null)[] = [];
  apiServer.use(
    http.post(PINS, async ({ request }) => {
      keys.push(request.headers.get("Idempotency-Key"));
      bodies.push(await request.json());
      return HttpResponse.json(answer, { status: 201 });
    }),
  );
  return { bodies, keys };
}

/** The screen, with one block on Monday at 09:00 and one on Tuesday. */
async function renderWeek(view = buildWeekView()) {
  const reads = installWeekReads(view);
  renderAt(WEEK_PATH);
  await screen.findByLabelText(`${LEETCODE} · Career`);
  return reads;
}

function blockOf(title: string): HTMLElement {
  return screen.getByLabelText(`${title} · Career`);
}

/** A drag from a block to a wall-clock minute, released inside the column. */
function dragTo(block: HTMLElement, minutes: number): void {
  fireEvent.pointerDown(block, { clientY: offsetOf(540) });
  fireEvent.pointerMove(window, { clientY: offsetOf(minutes) });
  fireEvent.pointerUp(window);
}

describe("the drag is discrete", () => {
  it("marks the grid as dragging and draws the hairline, and does not move the block", async () => {
    await renderWeek();
    /* THE RELEASE AT THE END OF THIS TEST IS A REAL DROP, so the route has to be installed even though nothing here
     * asserts the request: an unhandled write errors under `onUnhandledRequest: "error"`, and the rollback that
     * follows it runs after the cache has been torn down. Two tests in this file turned the whole suite red that way. */
    recordPins();
    const block = blockOf(LEETCODE);
    const before = block.getAttribute("style");

    fireEvent.pointerDown(block, { clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(780) });

    expect(document.querySelector(".week-grid")).toHaveAttribute("data-dragging");
    /* THE MARKER IS WHAT MOVES. The block's own box is byte-identical to what it was before the pointer went down. */
    expect(block.getAttribute("style")).toBe(before);
    const marker = document.querySelector(".week-insertion");
    expect(marker).not.toBeNull();
    expect(marker?.textContent).toBe("13:00");

    fireEvent.pointerUp(window);
  });

  it("snaps the marker to the quarter hour under the cursor", async () => {
    await renderWeek();
    recordPins();
    const block = blockOf(LEETCODE);

    fireEvent.pointerDown(block, { clientY: offsetOf(540) });
    /* Seven minutes past the quarter: the marker states the quarter, not the minute. */
    fireEvent.pointerMove(window, { clientY: offsetOf(787) });

    expect(document.querySelector(".week-insertion")?.textContent).toBe("13:00");
    fireEvent.pointerUp(window);
  });

  it("posts the pin on release, with an Idempotency-Key, and clears the marker", async () => {
    await renderWeek();
    const pins = recordPins();

    dragTo(blockOf(LEETCODE), 780);

    await waitFor(() => expect(pins.bodies).toHaveLength(1));
    expect(pins.bodies[0]).toEqual({
      blockId: BLOCK_LEETCODE,
      start: "2026-02-09T13:00:00.000Z",
    });
    expect(pins.keys[0]).toMatch(/^[0-9a-f-]{36}$/);
    expect(document.querySelector(".week-insertion")).toBeNull();
    expect(document.querySelector("[data-dragging]")).toBeNull();
  });

  it("moves the block and shows the pin glyph on the same redraw, before the api answers", async () => {
    await renderWeek();
    const pins = recordPins();

    dragTo(blockOf(LEETCODE), 780);

    /* THE OPTIMISTIC FRAME. The server's pin placement is exactly what was requested, so the block is drawn at its
     * new time and marked as the reader's own edit without waiting for the response. */
    await waitFor(() => expect(blockOf(LEETCODE)).toHaveAttribute("data-pinned"));
    expect(pins.bodies).toHaveLength(1);
  });

  it("consumes the operation the response carries, so the currency says solving at once", async () => {
    await renderWeek();
    recordPins(buildPinned({ operation: buildOperation({ status: "pending" }) }));
    expect(screen.getByText("91 blocks")).toBeInTheDocument();

    dragTo(blockOf(LEETCODE), 780);

    /* The third member of the response. A read cannot know about a solve the mutation that answered created, so a
     * screen that waited for the first event would say `current` while a solve was already due. */
    await waitFor(() => expect(screen.getByText("91 · solving")).toBeInTheDocument());
  });
});

describe("the drag that issues no request", () => {
  it("cancels on Escape, with no request and no marker", async () => {
    await renderWeek();
    const pins = recordPins();
    const block = blockOf(LEETCODE);

    fireEvent.pointerDown(block, { clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(780) });
    fireEvent.keyDown(window, { key: "Escape" });
    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
    expect(document.querySelector(".week-insertion")).toBeNull();
    expect(blockOf(LEETCODE)).not.toHaveAttribute("data-pinned");
  });

  /* THE PRESS POSITION IS THE WHOLE OF THIS CASE, and the first version of the test got it wrong: pressing at the
   * block's own start meant the SECOND guard caught the release, so the test passed with the rule it names deleted.
   * A press inside the block, one pixel under a rounding midpoint, is the position where a rounded quarter flips on
   * the smallest possible movement, which is what the travel floor exists for. */
  it("is a no-op for a jittery pointer, because a jitter is not a preference", async () => {
    await renderWeek();
    const pins = recordPins();
    /* 09:07:24, just under the 09:00/09:15 midpoint: the marker reads 09:00 here and 09:15 one pixel lower. */
    const midpoint = offsetOf(547.4);

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: midpoint });
    fireEvent.pointerMove(window, { clientY: midpoint + 1 });
    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
  });

  /* THE HARM THIS CLOSES, SWEPT RATHER THAN SAMPLED. A press anywhere in the block with an ordinary trackpad slop
   * must write nothing: `onClick` and `onPointerDown` are on the same element, so the documented way to SELECT a
   * block would otherwise move it, and a pin is a hard constraint the solver honours and a training label the
   * learning layer fits against. Before the travel floor, 6 of these 75 press positions posted a pin, at starts from
   * 09:15 to 10:30: up to a full block height away from where the block sits. */
  it("writes nothing from any press position in the block with a three-pixel slop", async () => {
    await renderWeek();
    const pins = recordPins();
    const block = blockOf(LEETCODE);
    const top = offsetOf(540);
    const bottom = offsetOf(630);
    let presses = 0;

    for (let y = Math.ceil(top); y <= Math.floor(bottom); y += 1) {
      presses += 1;
      fireEvent.pointerDown(block, { clientY: y });
      fireEvent.pointerMove(window, { clientY: y + SLOP_PX });
      fireEvent.pointerUp(window);
    }

    expect(presses).toBeGreaterThan(70);
    await settle();
    expect(pins.bodies).toEqual([]);
  });

  /* THE FLOOR IS NOT A REFUSAL OF EVERY DRAG, which is the control the sweep above needs: one snap step of travel is
   * the smallest movement that can mean a placement, and just past it the pin is posted. A pixel of slack rather than
   * the exact figure, because `(y + step) - y` is not bit-identical to `step` and a test pinned to a knife edge
   * measures the arithmetic of doubles rather than the rule. The figure is the drag's own, so the test cannot drift
   * from the floor it is testing. */
  it("posts on a release a snap step from the press, which is the smallest travel that means one", async () => {
    await renderWeek();
    const pins = recordPins();
    const from = offsetOf(540);

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: from });
    fireEvent.pointerMove(window, { clientY: from + travelFloorPx(PX_PER_MIN) + 1 });
    fireEvent.pointerUp(window);

    await waitFor(() => expect(pins.bodies).toHaveLength(1));
    expect(pins.bodies[0]).toMatchObject({ start: "2026-02-09T09:15:00.000Z" });
  });

  /* THE HAIRLINE STATES WHAT THE RELEASE WILL DO, which below the floor is "nothing moves". A marker at 09:15 over a
   * release that keeps 09:00 is the two halves of one rule disagreeing, in exactly the band the floor created. */
  it("holds the hairline at the block's own quarter while the travel is under the floor", async () => {
    await renderWeek();
    recordPins();
    /* 09:07:24, just under the 09:00/09:15 midpoint: one pixel lower is a different quarter under the cursor. */
    const midpoint = offsetOf(547.4);

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: midpoint });
    fireEvent.pointerMove(window, { clientY: midpoint + 1 });

    expect(document.querySelector(".week-insertion")?.textContent).toBe("09:00");

    fireEvent.pointerMove(window, { clientY: midpoint + travelFloorPx(PX_PER_MIN) + 1 });

    expect(document.querySelector(".week-insertion")?.textContent).toBe("09:30");
    fireEvent.pointerUp(window);
  });

  /* THE PLATFORM TAKING THE POINTER AWAY IS NOT A DROP. Without this the drag stayed live after a `pointercancel`,
   * the marker stayed drawn, and the NEXT release posted a pin at whatever quarter the cursor then held. */
  it("cancels on pointercancel, and a later release states nothing", async () => {
    await renderWeek();
    const pins = recordPins();

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(780) });
    fireEvent.pointerCancel(window);

    expect(document.querySelector(".week-insertion")).toBeNull();
    expect(document.querySelector("[data-dragging]")).toBeNull();

    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
  });

  /* A SECONDARY-BUTTON PRESS OPENS A CONTEXT MENU and delivers no release the page can pair with it, so a drag begun
   * on one is a drag that stays live. */
  it("does not begin on a secondary button", async () => {
    await renderWeek();
    const pins = recordPins();

    fireEvent.pointerDown(blockOf(LEETCODE), { button: 2, clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(780) });

    expect(document.querySelector("[data-dragging]")).toBeNull();
    expect(document.querySelector(".week-insertion")).toBeNull();

    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
  });

  it("cancels when the pointer is released above the column it started in", async () => {
    await renderWeek();
    const pins = recordPins();

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: offsetOf(540) });
    /* Above the canvas: the reader has stated no placement, and clamping to the top edge would turn a slip into a
     * hard constraint on the solver. */
    fireEvent.pointerMove(window, { clientY: -40 });
    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
    expect(document.querySelector(".week-insertion")).toBeNull();
  });

  /* THE HORIZONTAL AXIS, WHICH THE VERTICAL CASE ABOVE DOES NOT COVER. `clientX` was read nowhere in the drag, so a
   * release beside the starting column was not outside anything: it was read against that column, and dragging
   * Monday's block over Tuesday at 13:00 posted MONDAY 13:00 -- a placement in a day the reader had left.
   *
   * WHAT THIS TEST CAN AND CANNOT SEE. The stubbed box is the SAME for every canvas, so no test here can tell one
   * column from another: what is asserted is that a position outside the origin box horizontally states nothing, not
   * that the position was over Tuesday. Whether a drag should instead RETARGET to the column under the cursor is
   * ticket 1494, and a real box per column is on 1493's list. */
  it("cancels when the pointer is released beside the column it started in", async () => {
    await renderWeek();
    const pins = recordPins();

    fireEvent.pointerDown(blockOf(LEETCODE), { clientX: 60, clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientX: 620, clientY: offsetOf(780) });
    fireEvent.pointerUp(window);

    await settle();
    expect(pins.bodies).toEqual([]);
    expect(document.querySelector(".week-insertion")).toBeNull();
  });
});

describe("the keyboard equivalent of the drag", () => {
  it("Shift+Down pins fifteen minutes later, and the pin is the same request a drop makes", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");

    await waitFor(() => expect(pins.bodies).toHaveLength(1));
    /* Byte for byte the shape a drop sends: one route, one body, one path. There is no second way to pin. */
    expect(pins.bodies[0]).toEqual({
      blockId: BLOCK_LEETCODE,
      start: "2026-02-09T09:15:00.000Z",
    });
    expect(pins.keys[0]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("Shift+Up pins fifteen minutes earlier", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("{Shift>}{ArrowUp}{/Shift}");

    await waitFor(() => expect(pins.bodies).toHaveLength(1));
    expect(pins.bodies[0]).toMatchObject({ start: "2026-02-09T08:45:00.000Z" });
  });

  it("does nothing with no block selected, rather than pinning one the reader was not looking at", async () => {
    await renderWeek();
    const pins = recordPins();

    await userEvent.keyboard("{Shift>}{ArrowDown}{/Shift}");

    await settle();
    expect(pins.bodies).toEqual([]);
  });

  it("does nothing on a bare arrow, which belongs to the scroll", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("{ArrowDown}");

    await settle();
    expect(pins.bodies).toEqual([]);
  });
});

describe("p toggles a pin", () => {
  it("pins the selected block where it already is, which a drop can never do", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("p");

    await waitFor(() => expect(pins.bodies).toHaveLength(1));
    expect(pins.bodies[0]).toMatchObject({ start: "2026-02-09T09:00:00.000Z" });
  });

  it("releases the pin the week holds for the block, by the identifier the payload states", async () => {
    const pinned = buildWeekView({
      live: buildPlan({
        blocks: [
          buildBlock({ pinned: true }),
          buildBlock({
            id: BLOCK_APPLICATION,
            title: APPLICATION,
            interval: { start: monday("19:00"), end: monday("19:30") },
          }),
        ],
      }),
      pins: [buildPin({ id: "9b3d5f01-0000-4000-8000-0000000000aa" })],
    });
    await renderWeek(pinned);
    const removed: string[] = [];
    apiServer.use(
      http.delete(`${PINS}/:pinId`, ({ params }) => {
        removed.push(String(params.pinId));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("p");

    await waitFor(() => expect(removed).toEqual(["9b3d5f01-0000-4000-8000-0000000000aa"]));
  });

  /* A CHORD IS ONE GESTURE, and `p` names no screen: `g p` must reach no binding. A stray confirmation on the Today
   * screen is correctable; a stray pin is a hard constraint the solver then honours. */
  it("does not fire on g p, because the chord consumed the keystroke", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("gp");

    await settle();
    expect(pins.bodies).toEqual([]);
  });
});

describe("a refused pin", () => {
  /* THE ROLLBACK BRANCH, WHICH HAD NO TEST OF ITS OWN AND WAS BEING REACHED BY ACCIDENT. Two tests in this file
   * released without installing the route, so each fired an unhandled write, took this branch, and turned the whole
   * suite red by re-reading the week after the cache had been torn down. The branch is right and now it is asserted:
   * the plan of record never held the optimistic placement, so the honest recovery is to read the week again. */
  it("reads the week again, so the optimistic placement does not outlive the refusal", async () => {
    const reads = await renderWeek();
    apiServer.use(
      http.post(PINS, () =>
        HttpResponse.json(
          {
            type: "syncr:conflict",
            title: "Conflict",
            status: 409,
            detail: "That block has already begun, so it cannot be pinned.",
          },
          { status: 409 },
        ),
      ),
    );
    const before = reads.weekReads();

    dragTo(blockOf(LEETCODE), 780);

    await waitFor(() => expect(reads.weekReads()).toBe(before + 1));
    /* The reason is the api's own, at panel volume: the reader's plan is untouched and the sentence says which. */
    expect(
      await screen.findByText("That block has already begun, so it cannot be pinned."),
    ).toBeInTheDocument();
  });
});

describe("a late response", () => {
  /* TWO PINS IN QUICK SUCCESSION CAN ANSWER OUT OF ORDER, and the earlier verdict describes inputs the week has moved
   * past. Applying it would show a shortfall that has already been superseded beside a plan that has not. */
  it("for an older input version is discarded, and the newer verdict stands", async () => {
    await renderWeek();
    const answers = [
      buildPinned({
        verdict: buildVerdict({
          inputVersion: 9,
          shortfalls: [
            {
              kind: "deadline_capacity",
              minutes: 80,
              against: ["The newer reading"],
              honoring: [],
              deadline: null,
              areaId: null,
            },
          ],
          tradeoffs: [],
        }),
        operation: buildOperation({ id: "0f9b2c1e-0000-4000-8000-00000000000a" }),
      }),
      buildPinned({
        verdict: buildVerdict({
          inputVersion: 5,
          shortfalls: [
            {
              kind: "deadline_capacity",
              minutes: 300,
              against: ["The stale reading"],
              honoring: [],
              deadline: null,
              areaId: null,
            },
          ],
          tradeoffs: [],
        }),
      }),
    ];
    let answered = 0;
    apiServer.use(
      http.post(PINS, () => {
        const body = answers[Math.min(answered, answers.length - 1)];
        answered += 1;
        return HttpResponse.json(body, { status: 201 });
      }),
    );

    dragTo(blockOf(LEETCODE), 780);
    await waitFor(() => expect(screen.getByText("The newer reading")).toBeInTheDocument());

    dragTo(blockOf(APPLICATION), 900);

    await waitFor(() => expect(answered).toBe(2));
    expect(screen.getByText("The newer reading")).toBeInTheDocument();
    expect(screen.queryByText("The stale reading")).not.toBeInTheDocument();
  });
});
