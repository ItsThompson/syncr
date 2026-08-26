/* The ledger as a reader meets it: the band's figures, the two runs of rows, and the four surfaces the
 * screen draws when there is no ledger to draw.
 *
 * WHAT THE OUTCOME CONTROLS DO IS THE OTHER FILE. This one is about the reading. */

import { screen, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, readyz } from "../../../testing/apiStub";
import { renderSignedInAt } from "../../../testing/renderRoute";
import { AHEAD_TITLE, BEHIND_TITLE } from "../labels";
import {
  buildAreas,
  buildDay,
  buildEmptyDay,
  buildGymRow,
  buildOutcome,
  buildRow,
} from "./fixtures";
import { hostToday, onHostToday, renderToday } from "./render";

const origin = window.location.origin;

describe("the day band", () => {
  it("states the date, the counts, and the two acts that belong to the day", async () => {
    await renderToday(onHostToday(buildDay()));

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Today");
    /* The band names the day, the clock it was drawn at, and the zone both are read in, which is the
       response's own zone rather than the host's. */
    const band = screen.getByRole("heading", { level: 1 }).parentElement;
    expect(band?.textContent).toContain(String(new Date().getDate()));
    expect(band?.textContent).toContain("Europe/London");

    expect(screen.getByText("blocks").parentElement).toHaveTextContent("4");
    expect(screen.getByText("presumed complete").parentElement).toHaveTextContent("4");
    const confirm = screen.getByRole("button", { name: /Confirm the day/ });
    expect(confirm).toBeEnabled();
    /* The keystroke is advertised INSIDE the control it triggers, which is where a hint belongs: the mark takes
       the ink of the surface it lands on, so the ink rank's own fill no longer swallows it. */
    expect(within(confirm).getByText("c", { selector: "kbd" })).toBeInTheDocument();
  });

  /* The count is the api's own figure over the last 28 days, and the rows are today's. The fixture's own row count is
     read here rather than restated, so a fixture that gains or loses a row cannot quietly come to agree with the
     served figure and leave this case passing on nothing. */
  it("reads the count of unconfirmed days from the response rather than counting rows", async () => {
    const day = buildDay({ unconfirmedDays: 3 });
    const rowsDrawn = day.behind.length + day.ahead.length;
    expect(rowsDrawn, "the drawn rows must imply a figure the response does not serve").not.toBe(
      day.unconfirmedDays,
    );
    await renderToday(onHostToday(day));

    const cell = (await screen.findByText("unconfirmed days")).parentElement;
    expect(cell?.querySelector(".stat-cell__figure")?.textContent).toBe(
      String(day.unconfirmedDays),
    );
  });

  it("offers a backfill that states how many days it would settle", async () => {
    await renderToday(onHostToday(buildDay({ unconfirmedDays: 3 })));

    expect(await screen.findByRole("button", { name: "Backfill 3 days" })).toBeInTheDocument();
  });

  it("offers no backfill when no earlier day is outstanding", async () => {
    await renderToday(onHostToday(buildDay({ unconfirmedDays: 0 })));

    await screen.findByText(BEHIND_TITLE);
    expect(screen.queryByRole("button", { name: /Backfill/ })).not.toBeInTheDocument();
  });

  it("says an unconfirmed day is unconfirmed, at informational volume", async () => {
    await renderToday(onHostToday(buildDay()));

    const notice = await screen.findByRole("status", { name: "This day is not confirmed" });
    expect(notice).toHaveClass("notice--info");
    expect(notice).toHaveTextContent("excluded from reviews and from learning");
  });

  it("says when the day was confirmed, and then says nothing further about it", async () => {
    const settled = buildOutcome({ confirmedAt: "2026-02-09T20:41:00+00:00" });
    await renderToday(
      onHostToday(
        buildDay({
          behind: [buildGymRow({ outcome: settled })],
          ahead: [],
          blockCount: 1,
          presumedCount: 0,
          confirmedAt: "2026-02-09T20:41:00+00:00",
        }),
      ),
    );

    expect((await screen.findByText("confirmed")).parentElement).toHaveTextContent("20:41");
    expect(screen.queryByText("This day is not confirmed")).not.toBeInTheDocument();
  });
});

describe("the two sections", () => {
  it("groups the rows around now, as the api split them", async () => {
    await renderToday(onHostToday(buildDay()));

    const behind = (await screen.findByText(BEHIND_TITLE)).closest("section");
    const ahead = screen.getByText(AHEAD_TITLE).closest("section");

    expect(within(behind as HTMLElement).getByText("Sleep")).toBeInTheDocument();
    expect(within(behind as HTMLElement).getByText("Gym \u00B7 Chest & Back")).toBeInTheDocument();
    expect(within(ahead as HTMLElement).getByText("Leetcode")).toBeInTheDocument();
    expect(within(behind as HTMLElement).queryByText("Leetcode")).not.toBeInTheDocument();
  });

  it("renders both sections even when one holds nothing", async () => {
    await renderToday(
      onHostToday(buildDay({ behind: [], ahead: [buildRow()], blockCount: 1, presumedCount: 1 })),
    );

    const behind = (await screen.findByText(BEHIND_TITLE)).closest("section");
    expect(
      within(behind as HTMLElement).getByText("No block of this day has ended yet."),
    ).toBeInTheDocument();
    expect(screen.getByText(AHEAD_TITLE)).toBeInTheDocument();
  });

  it("says the run is over when every block of the day has ended", async () => {
    await renderToday(
      onHostToday(buildDay({ behind: [buildRow()], ahead: [], blockCount: 1, presumedCount: 1 })),
    );

    const ahead = (await screen.findByText(AHEAD_TITLE)).closest("section");
    expect(
      within(ahead as HTMLElement).getByText("Every block of this day has ended."),
    ).toBeInTheDocument();
  });

  it("reads a row with nothing said about it as presumed behind now and planned ahead of it", async () => {
    await renderToday(onHostToday(buildDay()));

    const behind = (await screen.findByText(BEHIND_TITLE)).closest("section");
    const ahead = screen.getByText(AHEAD_TITLE).closest("section");

    expect(within(behind as HTMLElement).getAllByText("presumed")).toHaveLength(2);
    expect(within(ahead as HTMLElement).getAllByText("planned")).toHaveLength(2);
  });
});

describe("a ledger row", () => {
  it("shows the interval, the duration in minutes, the Area with its name, and the title", async () => {
    await renderToday(onHostToday(buildDay()));

    const row = (await screen.findByText("Leetcode")).closest(".ledger__row");
    expect(row).not.toBeNull();
    const cells = row as HTMLElement;

    expect(cells.querySelector(".ledger__time")).toHaveTextContent("13:30\u201317:00");
    expect(cells.querySelector(".ledger__duration")).toHaveTextContent("210m");
    /* The chip carries no text: the name beside it is what identifies the Area, and the pair is what the
       row takes. */
    expect(cells.querySelector(".ledger__area")).toHaveTextContent("Career");
    expect(cells.querySelector(".ledger__area .area-chip")).not.toBeNull();
  });

  it("reads every time in the zone the day's bounds were resolved in", async () => {
    await renderToday(onHostToday(buildDay({ zone: "Pacific/Kiritimati" })));

    const row = (await screen.findByText("Leetcode")).closest(".ledger__row");
    expect((row as HTMLElement).querySelector(".ledger__time")).toHaveTextContent(
      "03:30\u201307:00",
    );
  });

  /* Prep and transit are blocks rather than bands: they appear here, they carry their Area, and they take
     an outcome like any other row. */
  it("renders a transit block as an ordinary row with its Area and its controls", async () => {
    await renderToday(onHostToday(buildDay()));

    const row = (await screen.findByText("Go Home")).closest(".ledger__row") as HTMLElement;

    expect(row.querySelector(".ledger__area")).toHaveTextContent("Career");
    expect(within(row).getByRole("button", { name: /skip/ })).toBeInTheDocument();
  });

  it("leaves the Area column empty for a block that carries no Area", async () => {
    await renderToday(onHostToday(buildDay()));

    const row = (await screen.findByText("Sleep")).closest(".ledger__row") as HTMLElement;

    expect(row.querySelector(".ledger__area")).toBeEmptyDOMElement();
  });

  /* An Area the list no longer holds keeps its name: a chip without an assigned pigment would be a colour
     this screen invented, but the name is what identifies an Area past the ramp's twelve steps anyway. */
  it("draws the name without a chip for an Area the areas list does not hold", async () => {
    await renderToday(
      onHostToday(
        buildDay({
          behind: [],
          ahead: [buildRow({ areaId: "3f1b7a3c-9999-4c8e-9a11-0000000000zz" })],
          blockCount: 1,
          presumedCount: 1,
        }),
      ),
    );

    const row = (await screen.findByText("Leetcode")).closest(".ledger__row") as HTMLElement;
    expect(row.querySelector(".ledger__area .area-chip")).toBeNull();
    expect(row.querySelector(".ledger__area")).toHaveTextContent("Career");
  });

  it("shows the minutes a partial really took beside the planned figure", async () => {
    await renderToday(
      onHostToday(
        buildDay({
          behind: [buildRow({ outcome: buildOutcome({ state: "partial", actualMinutes: 145 }) })],
          ahead: [],
          blockCount: 1,
          presumedCount: 0,
        }),
      ),
    );

    expect(await screen.findByText("partial \u00B7 145m of 210m planned")).toBeInTheDocument();
  });

  it("shows both the planned interval and the actual one for a moved outcome", async () => {
    await renderToday(
      onHostToday(
        buildDay({
          behind: [
            buildRow({
              outcome: buildOutcome({
                state: "moved",
                actualInterval: {
                  start: "2026-02-09T18:00:00+00:00",
                  end: "2026-02-09T19:30:00+00:00",
                },
              }),
            }),
          ],
          ahead: [],
          blockCount: 1,
          presumedCount: 0,
        }),
      ),
    );

    const row = (await screen.findByText("Leetcode")).closest(".ledger__row") as HTMLElement;
    expect(row.querySelector(".ledger__time")).toHaveTextContent("13:30\u201317:00");
    expect(within(row).getByText("moved \u00B7 ran 18:00\u201319:30")).toBeInTheDocument();
  });

  it("reads a confirmed presumption as recorded, which is what confirming a day does to it", async () => {
    await renderToday(
      onHostToday(
        buildDay({
          behind: [
            buildGymRow({
              outcome: buildOutcome({
                state: "presumed",
                confirmedAt: "2026-02-09T20:41:00+00:00",
              }),
            }),
          ],
          ahead: [],
          blockCount: 1,
          presumedCount: 1,
          confirmedAt: "2026-02-09T20:41:00+00:00",
        }),
      ),
    );

    expect(await screen.findByText("recorded")).toBeInTheDocument();
  });
});

describe("the premise", () => {
  it("states that check-off is optional and which row the keys act on", async () => {
    await renderToday(onHostToday(buildDay()));

    const panel = (await screen.findByText("Per-block check-off is optional")).closest("section");
    expect(panel).toHaveTextContent("presumed complete unless you say otherwise");
    expect(panel).toHaveTextContent("including the ones still ahead in it");
    expect(panel).toHaveTextContent("Focus a row");
  });
});

describe("nothing to draw", () => {
  it("names that no blocks are planned, and offers no confirmation", async () => {
    await renderToday(onHostToday(buildEmptyDay()));

    expect(await screen.findByText("No blocks are planned for this day")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Confirm the day/ })).toBeDisabled();
    expect(screen.queryByText(BEHIND_TITLE)).not.toBeInTheDocument();
  });

  it("says what it is waiting for, and nothing spins", async () => {
    apiServer.use(
      readyz(),
      http.get(`${origin}/api/v1/areas`, () => HttpResponse.json(buildAreas())),
      /* A request that never answers, so the pending reading is deterministic. */
      http.get(`${origin}/api/v1/days/:date`, () => new Promise<never>(() => {})),
    );
    await renderSignedInAt("/today");

    expect(await screen.findByText("Reading today")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  /* The date a tenant's zones do not hold is refused by the api rather than answered with an empty ledger,
     and what reaches the reader is the api's own sentence naming the date and the zone. */
  it("names which read failed and keeps the api's own sentence", async () => {
    apiServer.use(
      readyz(),
      http.get(`${origin}/api/v1/areas`, () => HttpResponse.json(buildAreas())),
      jsonHandler(`/api/v1/days/${hostToday()}`, {
        status: 422,
        body: {
          type: "syncr:validation-failed",
          title: "Validation failed",
          status: 422,
          detail:
            "2011-12-30 does not exist in Pacific/Apia: local midnight on that date and local " +
            "midnight on the next name the same instant, so the day has no length.",
        },
      }),
    );
    await renderSignedInAt("/today");

    expect(await screen.findByText("The day could not be read")).toBeInTheDocument();
    expect(screen.getByText(/does not exist in Pacific\/Apia/)).toBeInTheDocument();
  });
});
