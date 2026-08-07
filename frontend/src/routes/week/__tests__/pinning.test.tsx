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
import { GRID_H_PX } from "../../../ui/domain";
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
    const { container } = await (async () => {
      await renderWeek();
      return { container: document.body };
    })();
    const block = blockOf(LEETCODE);
    const before = block.getAttribute("style");

    fireEvent.pointerDown(block, { clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(780) });

    expect(container.querySelector(".week-grid")).toHaveAttribute("data-dragging");
    /* THE MARKER IS WHAT MOVES. The block's own box is byte-identical to what it was before the pointer went down. */
    expect(block.getAttribute("style")).toBe(before);
    const marker = container.querySelector(".week-insertion");
    expect(marker).not.toBeNull();
    expect(marker?.textContent).toBe("13:00");

    fireEvent.pointerUp(window);
  });

  it("snaps the marker to the quarter hour under the cursor", async () => {
    await renderWeek();
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

    expect(pins.bodies).toEqual([]);
    expect(document.querySelector(".week-insertion")).toBeNull();
    expect(blockOf(LEETCODE)).not.toHaveAttribute("data-pinned");
  });

  it("is a no-op on the same quarter hour, because a jittery pointer is not a preference", async () => {
    await renderWeek();
    const pins = recordPins();

    /* Down at 09:00 and up four minutes later, which snaps back to 09:00: the block already begins there. */
    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: offsetOf(540) });
    fireEvent.pointerMove(window, { clientY: offsetOf(544) });
    fireEvent.pointerUp(window);

    expect(pins.bodies).toEqual([]);
  });

  it("cancels when the pointer is released outside the column it started in", async () => {
    await renderWeek();
    const pins = recordPins();

    fireEvent.pointerDown(blockOf(LEETCODE), { clientY: offsetOf(540) });
    /* Above the canvas: the reader has stated no placement, and clamping to the top edge would turn a slip into a
     * hard constraint on the solver. */
    fireEvent.pointerMove(window, { clientY: -40 });
    fireEvent.pointerUp(window);

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

    expect(pins.bodies).toEqual([]);
  });

  it("does nothing on a bare arrow, which belongs to the scroll", async () => {
    await renderWeek();
    const pins = recordPins();
    await userEvent.click(blockOf(LEETCODE));

    await userEvent.keyboard("{ArrowDown}");

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

    expect(pins.bodies).toEqual([]);
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
