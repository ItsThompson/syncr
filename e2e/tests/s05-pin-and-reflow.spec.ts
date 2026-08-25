/* S5, pin and reflow: a discrete drag across a real day-column boundary.
 *
 * WHY THIS IS A BROWSER CASE AND NOTHING ELSE CAN BE. The drag reads the pointer against the box of the
 * column it pressed in, and jsdom hands every canvas the same stubbed box, so the unit tier cannot see the
 * horizontal axis at all: a position "over the next column" is indistinguishable from one over the origin.
 * Only a laid-out grid can show a pointer crossing a real boundary, and only Chromium delivers the trusted
 * pointer stream a real `setPointerCapture` captures.
 *
 * THE FOUR OBSERVATIONS, AND WHAT EACH MEANS MEASURABLY:
 *
 *   the block does not follow the cursor -- at every sampled pointer position, including one over the next
 *     column, the dragged block's box is the box it had before the press;
 *   a hairline marker snaps to the quarter hour -- the one `.week-insertion` the grid draws while the
 *     pointer is inside the origin column names a :00/:15/:30/:45 reading and sits where that reading falls
 *     in the column's own geometry, and disappears entirely while the pointer is over the next column,
 *     because a pointer over another column states nothing;
 *   exactly ONE redraw happens on drop -- one mutation batch carries the marker's removal, the block's new
 *     position and its pin glyph together, and one painted frame shows all three with no painted state in
 *     between and no further block movement until the solved week lands;
 *   the verdict arrives on the same redraw -- the pin response's answer is one paint too: the verdict
 *     words and the plan currency's `solving` change in the same painted frame, moving no block, seconds
 *     before the worker has finished, rather than trailing behind a second load.
 *
 * WHICH WEEK, AND WHY. The observations need a verdict the pin VISIBLY answers, or the fourth asserts
 * nothing: on a week with no shortfall the words never change and a broken verdict path passes green.
 * `tight_capacity` is the fixture whose verdict a single pin moves -- its plan week reports a pre-deadline
 * shortfall, and lifting the deadline chunk by an hour shrinks it -- so the words the strip states are part
 * of what the gesture does. Which figure it moves is read off the pin's own response rather than named
 * here, because the arithmetic of that gap is another statement's job and a copy of it here would drift.
 *
 * WHERE THE BLOCK ENDS UP ON SCREEN. A pin on a task becomes a pending proposal, and the plan of record
 * keeps the solver's placement until it is approved, so the reflow the solve lands draws the chunk back
 * where it was: that revert is asserted as the one block movement after the verdict's frame, not worked
 * around, because it is the product's authority rule showing on the surface.
 *
 * HOW THE TIMELINE IS READ. A recorder installed before the press keeps two series: painted frames, diffed
 * per animation frame over the marker, every block's drawn position and glyph, the verdict words and the
 * plan currency; and mutation batches, classified by what they touched. Nothing sleeps: waits poll the api
 * and the rendered screen, because the drag itself is synchronous and the worker runs on its own clock.
 */

import { test, expect, usingFixture } from "./harness.ts";
import type { Page } from "@playwright/test";
import { HOME_ZONE } from "../src/config.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import { awaitTerminal, solveAndSettle } from "../src/harness/week.ts";

usingFixture("tight_capacity");
test.describe.configure({ mode: "serial" });

/** How far the drag lifts the chunk: four quarters, well past the one-snap-step travel floor. */
const LIFT_MINUTES = 60;

interface Frame {
  readonly t: number;
  /** Each drawn marker: `<top>|<reading>`. */
  readonly m: readonly string[];
  /** Each block: `<top>`, with `P` appended when it draws the pin glyph. */
  readonly b: readonly string[];
  readonly v: string | null;
  readonly cur: string | null;
  readonly d: string | null;
}

interface Batch {
  readonly t: number;
  readonly n: number;
  readonly tg: readonly string[];
}

/** The two series, installed before the press. A STRING because the harness's tsconfig carries no DOM lib,
 * which is why every reader in this suite is a string too. */
const INSTALL_RECORDER = `
(() => {
  window.__rec = { frames: [], batches: [] };
  const snapshot = () => ({
    m: [...document.querySelectorAll('.week-insertion')].map(
      (x) => x.style.top + '|' + (x.querySelector('.week-insertion__at')?.textContent ?? ''),
    ),
    b: [...document.querySelectorAll('.week-block')].map(
      (x) => x.style.top + (x.hasAttribute('data-pinned') ? 'P' : ''),
    ),
    v: document.querySelector('.week-strip__verdict')?.textContent ?? null,
    cur: document.querySelector('.stat-cell__sub')?.textContent ?? null,
    d: document.querySelector('.week-grid')?.getAttribute('data-dragging'),
  });
  let prev = '';
  const tick = () => {
    const s = snapshot();
    const key = JSON.stringify(s);
    if (key !== prev) {
      prev = key;
      window.__rec.frames.push({ t: Math.round(performance.now()), ...s });
    }
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  new MutationObserver((mutations) => {
    const targets = new Set();
    for (const mutation of mutations) {
      const el = mutation.target instanceof Element ? mutation.target : mutation.target.parentElement;
      if (el !== null) targets.add([...el.classList].slice(0, 2).join('.'));
    }
    window.__rec.batches.push({ t: Math.round(performance.now()), n: mutations.length, tg: [...targets] });
  }).observe(document.body, { subtree: true, attributes: true, childList: true, characterData: true });
})();
`;

/** Geometry of the drawn grid: each column canvas's box, and the origin column's hour-line tops. */
const READ_GEOMETRY = `(() => {
  const canvases = [...document.querySelectorAll('.week-day__canvas')];
  return {
    columns: canvases.map((c) => { const b = c.getBoundingClientRect(); return { l: b.left, r: b.right, t: b.top }; }),
    hours: [...canvases[0].querySelectorAll('.week-grid__line--hour')].map((h) => parseFloat(h.style.top)),
  };
})()`;

interface Drawn {
  /** Position among every `.week-block` in the document: how later reads address this exact element,
   * because a fixture names several blocks alike and a title alone would not pick one out. */
  readonly bi: number;
  readonly ci: number;
  /** The canvas-relative top the element is drawn at, which is what its inline style states. */
  readonly styleTop: number;
  readonly x: number;
  readonly y: number;
}

/** Where the named block is drawn. A STRING for the same reason every reader here is one: the harness
 * tsconfig carries no DOM lib, so the evaluated body is text. */
const readDrawnBlock = (page: Page, titlePrefix: string): Promise<Drawn> =>
  page.evaluate(
    `((prefix) => {
      const blocks = [...document.querySelectorAll('.week-block')];
      const el = blocks.find((candidate) =>
        (candidate.querySelector('.week-block__title')?.textContent ?? '').startsWith(prefix));
      if (!el) throw new Error('no block titled ' + prefix);
      const canvas = el.closest('.week-day__canvas');
      const box = el.getBoundingClientRect();
      return {
        bi: blocks.indexOf(el),
        ci: [...document.querySelectorAll('.week-day__canvas')].indexOf(canvas),
        styleTop: parseFloat(el.style.top),
        x: box.x,
        y: box.y,
      };
    })(${JSON.stringify(titlePrefix)})`,
  );

/** The one marker the grid is drawing right now: where it sits and what it states, or null. */
const readMarker = (page: Page): Promise<{ top: number; at: string } | null> =>
  page.evaluate(`(() => {
    const m = document.querySelector('.week-insertion');
    if (!m) return null;
    return {
      top: parseFloat(m.style.top),
      at: m.querySelector('.week-insertion__at')?.textContent ?? '',
    };
  })()`);

/** `1h15m`, `45m`, `2h`: the one spelling of a duration on this screen, which
 * `frontend/src/ui/domain/verdict-panel/verdict.ts` owns. Restated here because this case reads rendered
 * words, and the frontend's module is not importable from the harness. */
const figureOf = (minutes: number): string => {
  const whole = Math.max(0, Math.round(minutes));
  const hours = Math.floor(whole / 60);
  const rest = whole % 60;
  if (hours === 0) return `${rest}m`;
  if (rest === 0) return `${hours}h`;
  return `${hours}h${rest}m`;
};

test("S5, pin and reflow: a discrete drag across a real column boundary", async ({ api, page }) => {
  test.setTimeout(180_000);
  await page.setViewportSize({ width: 1600, height: 1000 });
  await solveAndSettle(api, planWeek());

  // THE CHUNK, AND THE PREMISE. The earliest unpinned task chunk has the clearest room above it, and the
  // case needs a shortfall to exist: without one, no pin could visibly answer the verdict.
  const before = await api.get<any>(`/api/v1/weeks/${planWeek()}`);
  const chunk = (before.live?.blocks ?? [])
    .filter((b: any) => b.origin === "task" && !b.pinned)
    .sort((a: any, b: any) => Date.parse(a.interval.start) - Date.parse(b.interval.start))[0];
  expect(chunk, "the solved week placed nothing a drag could lift").toBeDefined();
  expect(
    before.verdict.shortfalls.some((s: any) => s.minutes > 0),
    "the week reports no shortfall, so the verdict has nothing for a pin to answer",
  ).toBe(true);

  await page.goto(`/week?week=${planWeek()}`);
  await page.waitForSelector(".week-block");
  // The grid draws from a measurement that lands a frame or two after mount, and an early figure would pin
  // the case's geometry to a layout about to move under it. Wait until the drawn surface holds still across
  // two animation frames rather than sleeping a fixed amount.
  await page.waitForFunction(
    `(() => new Promise((resolve) => {
      const block = [...document.querySelectorAll('.week-block')][0];
      const canvas = document.querySelector('.week-day__canvas');
      if (!block || !canvas) { resolve(false); return; }
      const stable = () =>
        block.getBoundingClientRect().top === block.dataset.__top &&
        canvas.getBoundingClientRect().height === parseFloat(canvas.style.height);
      block.dataset.__top = String(block.getBoundingClientRect().top);
      requestAnimationFrame(() => requestAnimationFrame(() => { const ok = stable(); delete block.dataset.__top; resolve(ok); }));
    }))()`,
  );

  const geo = (await page.evaluate(READ_GEOMETRY)) as {
    columns: { l: number; r: number; t: number }[];
    hours: number[];
  };
  const pxPerMin = (geo.hours[1]! - geo.hours[0]!) / 60;
  expect(pxPerMin, "the drawn grid gave no usable scale").toBeGreaterThan(0);

  const titlePrefix = (chunk.title as string).slice(0, 12);
  const drawn = await readDrawnBlock(page, titlePrefix);
  const columnB = geo.columns[drawn.ci + 1];
  expect(columnB, "the block sits in the last column, with no boundary to cross").toBeDefined();

  // THE AIM. A release states the quarter its pointer sits in at the moment it lifts, and the pointer is
  // read against the column canvas: so the release point aims at the CENTRE of the quarter one hour above
  // the block's own start, computed from what the grid actually drew rather than from arithmetic about
  // what it should have drawn.
  const liftPx = LIFT_MINUTES * pxPerMin;
  const halfQuarterPx = 7.5 * pxPerMin;
  const releaseY = geo.columns[drawn.ci].t! + drawn.styleTop - liftPx + halfQuarterPx;
  const expectedStyleTop = drawn.styleTop - liftPx;

  // The wall clock the marker has to name if the geometry mapped the pointer correctly: the chunk's own
  // start, one hour earlier, read in the tenant's home zone.
  const expectedReading = new Intl.DateTimeFormat("en-GB", {
    timeZone: HOME_ZONE,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(Date.parse(chunk.interval.start) - LIFT_MINUTES * 60_000));

  /** The drawn block addressed by position, since a fixture names several blocks alike. */
  const blockByIndex = (
    page: Page,
    index: number,
  ): Promise<{ x: number; y: number; pinned: boolean; styleTop: number }> =>
    page.evaluate(
      `((i) => {
        const el = [...document.querySelectorAll('.week-block')][i];
        if (!el) return null;
        const box = el.getBoundingClientRect();
        return { x: box.x, y: box.y, pinned: el.hasAttribute('data-pinned'), styleTop: parseFloat(el.style.top) };
      })(${index})`,
    );

  const pressX = drawn.x + 40;
  const pressY = drawn.y + 6;

  await page.evaluate(INSTALL_RECORDER);

  let pinRequests = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("/pins")) pinRequests += 1;
  });

  // ---- THE DRAG ----
  await page.mouse.move(pressX, pressY);
  await page.mouse.down();
  await page.mouse.move(pressX, pressY + 2 * 15 * pxPerMin, { steps: 4 });
  await page.waitForTimeout(200);

  // OBSERVATION, MID-DRAG IN THE ORIGIN COLUMN: one marker, drawn once, naming a quarter.
  const midDrag = (await page.evaluate(`(() => ({
    dragging: document.querySelector('.week-grid')?.getAttribute('data-dragging'),
    markers: [...document.querySelectorAll('.week-insertion')].map((m) => ({
      top: parseFloat(m.style.top),
      at: m.querySelector('.week-insertion__at')?.textContent ?? '',
    })),
  }))()`)) as { dragging: string | null; markers: { top: number; at: string }[] };
  expect(midDrag.dragging, "pressing the block began no drag").not.toBeNull();

  // OBSERVATION, OVER THE NEXT COLUMN: the pointer crosses a real boundary, and the grid states nothing.
  await page.mouse.move(columnB!.l + 60, pressY, { steps: 8 });
  await page.waitForTimeout(200);
  const markersOverNextColumn = await page.evaluate(
    "document.querySelectorAll('.week-insertion').length",
  );
  expect(markersOverNextColumn, "a marker followed the pointer across the column boundary").toBe(0);
  const overNextColumn = await blockByIndex(page, drawn.bi);
  expect(
    [overNextColumn!.x, overNextColumn!.y],
    "the block followed the cursor across the boundary",
  ).toEqual([drawn.x, drawn.y]);
  expect(overNextColumn!.pinned, "the block pinned itself mid-drag").toBe(false);

  // Back inside the origin column, still dragging. Where the marker sits for a given pointer position is
  // read off the marker itself rather than derived here: the two arithmetics can disagree by a hair, and a
  // hair is a quarter at a boundary. The marker is the product's own statement of what a release will do,
  // so the aim walks onto the wanted line and holds there.
  const desiredMarkerTop = drawn.styleTop - liftPx;
  await page.mouse.move(pressX, releaseY, { steps: 6 });
  await page.waitForTimeout(200);
  let aim = await readMarker(page);
  expect(aim, "returning to the origin column drew no marker").not.toBeNull();
  for (
    let correction = 0;
    correction < 4 && Math.abs(aim!.top - desiredMarkerTop) >= 0.75;
    correction++
  ) {
    await page.mouse.move(pressX, releaseY - (aim!.top - desiredMarkerTop), { steps: 2 });
    await page.waitForTimeout(150);
    aim = await readMarker(page);
  }
  const backInOrigin = { markers: [aim] };

  // THE SNAP, AS GEOMETRY RATHER THAN WORDS: the marker sits where its reading falls. The distance down to
  // the hour line below it is the reading's own minutes within that hour, at the scale the grid draws at.
  const marker = backInOrigin.markers[0]!;
  expect(marker.at, "the marker did not name a quarter hour").toMatch(/^\d{2}:(00|15|30|45)$/);
  expect(marker.at, "the marker did not state the instant one hour above the block").toBe(
    expectedReading,
  );
  const hourBelow = Math.max(...geo.hours.filter((top) => top <= marker.top + 0.01));
  const minutesIntoHour = ((marker.top - hourBelow) / pxPerMin) % 60;
  expect(
    Math.abs(minutesIntoHour - Number(marker.at.slice(3))),
    "the marker sat off its stated quarter",
  ).toBeLessThan(0.5);

  // OBSERVATION, THROUGHOUT: the block never followed the cursor.
  const beforeRelease = await blockByIndex(page, drawn.bi);
  expect([beforeRelease!.x, beforeRelease!.y], "the block moved during the drag").toEqual([
    drawn.x,
    drawn.y,
  ]);

  // ---- THE DROP ----
  await page.evaluate(
    "window.__rec.batches.push({ t: Math.round(performance.now()), n: 0, tg: ['RELEASE'] })",
  );
  // Waited for by promise rather than polled afterwards: the optimistic frame paints the moment the
  // pointer lifts, which is BEFORE the request has answered, so the answer needs its own wait.
  const pinAnswered = page.waitForResponse(
    (response) => response.request().method() === "POST" && response.url().includes("/pins"),
  );
  await page.mouse.up();

  // The drop applied: THE dragged block drawn at the stated quarter with the glyph, addressed by position,
  // and the api holds a pin at exactly the lifted instant, computed against the column the drag pressed in
  // despite the crossing.
  await page.waitForFunction(
    `([top, index]) => {
      const el = [...document.querySelectorAll('.week-block')][index];
      return el !== null && el !== undefined && el.hasAttribute('data-pinned') &&
        Math.abs(parseFloat(el.style.top) - top) < 1;
    }`,
    [expectedStyleTop, drawn.bi],
  );
  expect(pinRequests, "the drop posted more than one pin").toBe(1);
  const pinReply = await pinAnswered;
  expect(pinReply.status(), "the pin was refused").toBe(201);
  const pinBody = (await pinReply.json()) as any;
  const pinMinutes = pinBody?.verdict?.shortfalls?.reduce(
    (sum: number, s: any) => sum + s.minutes,
    0,
  );
  expect(Number.isFinite(pinMinutes), "the pin response carried no shortfall figure").toBe(true);

  const stored = await api.get<any>(`/api/v1/weeks/${planWeek()}`);
  const heldPin = stored.pins.find((p: any) => p.blockId === chunk.id);
  expect(heldPin, "no pin was stored for the dropped block").toBeDefined();
  expect(Date.parse(heldPin.interval.start)).toBe(
    Date.parse(chunk.interval.start) - LIFT_MINUTES * 60_000,
  );

  // ---- EXACTLY ONE REDRAW ON DROP ----
  const { frames: framesSoFar, batches } = (await page.evaluate("window.__rec")) as {
    frames: Frame[];
    batches: Batch[];
  };
  const dropFrames = framesSoFar;
  const lastDraggingIndex = dropFrames.findLastIndex((f) => f.d !== null);
  expect(lastDraggingIndex, "the recorder never saw the drag").toBeGreaterThanOrEqual(0);
  const dropFrame = dropFrames[lastDraggingIndex + 1];
  expect(dropFrame, "no painted frame followed the release").toBeDefined();
  expect(dropFrame!.d, "the drop left the drag marked as live").toBeNull();
  expect(dropFrame!.m, "the marker outlived the release").toEqual([]);
  // One painted state between "dragging" and "dropped": the block at the stated quarter WITH the glyph,
  // and nothing else on the grid moved in that frame. A marker that leaves one frame before its block
  // moves, or a block that arrives a frame before its glyph, is a second redraw and turns red here.
  const previous = dropFrames[lastDraggingIndex]!;
  const changedEntries = dropFrame!.b.filter((entry, index) => entry !== previous.b[index]);
  expect(changedEntries, "the drop repainted more than the dropped block").toHaveLength(1);
  expect(changedEntries[0], "the drop frame drew the block without its pin glyph").toMatch(/P$/);
  expect(
    Math.abs(parseFloat(changedEntries[0]!) - expectedStyleTop),
    "the drop drew the block off its quarter",
  ).toBeLessThan(1);

  // And one mutation batch carried it: between the release and whatever touched the grid next, nothing
  // intervened, and that batch reached the canvas (marker), the block (position and glyph) and the grid's
  // own dragging attribute together.
  const releaseBatchIndex = batches.findIndex((batch) => batch.tg.includes("RELEASE"));
  const dropBatches = batches.slice(releaseBatchIndex + 1);
  const gridBatch = dropBatches.find((batch) =>
    batch.tg.some((t) => t.startsWith("week-day__canvas") || t.startsWith("week-block")),
  );
  expect(gridBatch, "no mutation batch applied the drop").toBeDefined();
  expect(
    gridBatch!.tg.some((t) => t.startsWith("week-day__canvas")),
    "the marker outlived the drop batch",
  ).toBe(true);
  expect(
    gridBatch!.tg.some((t) => t.startsWith("week-block")),
    "the drop batch never reached the block",
  ).toBe(true);
  expect(
    gridBatch!.tg.some((t) => t.startsWith("week-grid")),
    "the drop left data-dragging set",
  ).toBe(true);

  // ---- THE VERDICT ARRIVES ON THE SAME REDRAW, AND THE REFLOW FOLLOWS ----
  // The worker runs on its own clock, so the recording is read whole only once the operation has reached a
  // terminal state and the refetch it triggers has been painted. Everything from here on reads history.
  await awaitTerminal(api, pinBody.operation.id);

  let whole = framesSoFar;
  const timeline = (): { verdict: number; reflow: number } => {
    const verdictIndex = whole.findIndex((f, index) => index > 0 && f.v !== whole[index - 1]!.v);
    if (verdictIndex < 0) return { verdict: -1, reflow: -1 };
    const reflowIndexLocal = whole.findIndex(
      (f, index) => index > verdictIndex && f.b.join(",") !== whole[index - 1]!.b.join(","),
    );
    return { verdict: verdictIndex, reflow: reflowIndexLocal };
  };

  await expect
    .poll(
      async () => {
        const rec = (await page.evaluate("window.__rec")) as {
          frames: Frame[];
          batches: Batch[];
        };
        whole = rec.frames;
        return timeline().reflow;
      },
      { timeout: 15_000 },
    )
    .toBeGreaterThan(0);

  const { verdict: verdictFrameIndex, reflow: reflowIndex } = timeline();
  const frames = whole;

  expect(verdictFrameIndex, "the verdict words never changed").toBeGreaterThan(
    dropIndex(dropFrames, dropFrame!),
  );
  const verdictFrame = frames[verdictFrameIndex]!;
  expect(
    verdictFrame.cur ?? "",
    "the verdict changed alone, with no answer named beside it",
  ).toContain("solving");
  expect(verdictFrame.b.join(","), "the verdict's frame moved a block").toBe(
    previousOf(frames, verdictFrameIndex).b.join(","),
  );

  // One verdict paint, not a flicker: the words change once and hold...
  const laterVerdictChanges = frames.filter(
    (f, index) => index > verdictFrameIndex && f.v !== frames[index - 1]!.v,
  );
  expect(laterVerdictChanges, "the verdict words changed more than once").toEqual([]);
  // ...and they carry the figure the pin's own response stated, spelled the way the screen spells durations.
  expect(
    verdictFrame.v ?? "",
    "the verdict did not state the figure the pin's response carried",
  ).toContain(figureOf(pinMinutes as number));

  // The solved week landed and the plan of record takes the chunk back: the authority rule drawing itself.
  // It is the one block movement after the verdict's frame.
  expect(reflowIndex, "the settled week never repainted the grid").toBeGreaterThan(
    verdictFrameIndex,
  );
});

/** The index of a frame object, when an assertion wants "after the drop" by position rather than identity. */
function dropIndex(frames: readonly Frame[], dropFrame: Frame): number {
  const index = frames.indexOf(dropFrame);
  expect(index, "the drop frame vanished from the recording").toBeGreaterThanOrEqual(0);
  return index;
}

/** The frame painted immediately before `index`. */
function previousOf(frames: readonly Frame[], index: number): Frame {
  const previous = frames[index - 1];
  expect(previous, `no frame precedes ${index}`).toBeDefined();
  return previous!;
}
