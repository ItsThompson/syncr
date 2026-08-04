/* The route, as a smoke test: it renders the four tabs against representative data and does not throw.
 *
 * A ROUTE TEST IS DELIBERATELY THIN. Each tab's behaviour is asserted where the tab is, against props, and
 * asserting it again through the real route table and the real client would test the interceptor. What only this
 * test can say is that the route wires its nine reads to the tabs that need them, that the tab strip is what the
 * screen opens with, and that the page title is the serif one a destination claims. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { RequestHandler } from "msw";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler, readyz, recordingHandler } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import {
  SHAPE_WEEKDAY,
  TYPE_INTERVIEW,
  TYPE_LECTURE,
  buildAnchor,
  buildAnchorType,
  buildAreas,
  buildDayType,
  buildFixedHabit,
  buildHabit,
  buildLectureType,
  buildRoutine,
  buildShape,
  buildShapeSummary,
  buildSource,
  buildWeekPattern,
} from "./fixtures";

function screenHandlers(): RequestHandler[] {
  return [
    readyz(),
    jsonHandler("/api/v1/day-types", { status: 200, body: { dayTypes: [buildDayType()] } }),
    jsonHandler("/api/v1/templates", { status: 200, body: { templates: [buildShapeSummary()] } }),
    jsonHandler(`/api/v1/templates/${SHAPE_WEEKDAY}`, { status: 200, body: buildShape() }),
    jsonHandler("/api/v1/areas", { status: 200, body: buildAreas() }),
    jsonHandler("/api/v1/routines", { status: 200, body: { routines: [buildRoutine()] } }),
    jsonHandler("/api/v1/habits", {
      status: 200,
      body: { habits: [buildHabit(), buildFixedHabit()] },
    }),
    jsonHandler("/api/v1/week-pattern", { status: 200, body: buildWeekPattern() }),
    jsonHandler("/api/v1/anchor-types", {
      status: 200,
      body: { anchorTypes: [buildAnchorType(), buildLectureType()] },
    }),
    jsonHandler("/api/v1/calendar-sources", { status: 200, body: { sources: [buildSource()] } }),
    jsonHandler("/api/v1/anchors", {
      status: 200,
      body: { anchors: [buildAnchor()], nextCursor: null },
    }),
  ];
}

async function renderTemplates() {
  apiServer.use(...screenHandlers());
  renderAt("/templates");
  return screen.findByRole("tablist", { name: "Templates" });
}

describe("the templates route", () => {
  it("renders a serif page title, because a screen is a destination", async () => {
    await renderTemplates();

    const title = screen.getByRole("heading", { level: 1 });
    expect(title).toHaveTextContent("Templates");
    expect([...title.classList]).toContain("font-serif");
  });

  it("opens on four tabs, in the order the ticket names them", async () => {
    const strip = await renderTemplates();

    const labels = within(strip)
      .getAllByRole("tab")
      .map((tab) => tab.textContent);

    expect(labels[0]).toContain("Day shapes");
    expect(labels[1]).toContain("Week pattern");
    expect(labels[2]).toContain("Habits");
    expect(labels[3]).toContain("Anchor types");
  });

  it("counts each list on its own tab once the list arrives", async () => {
    const strip = await renderTemplates();

    await waitFor(() =>
      expect(within(strip).getByRole("tab", { name: /Habits/ })).toHaveTextContent("2"),
    );
    expect(within(strip).getByRole("tab", { name: /Anchor types/ })).toHaveTextContent("2");
  });

  it("selects the first day shape, so the editor is not empty on arrival", async () => {
    await renderTemplates();

    await waitFor(() =>
      expect(screen.getByRole("table", { name: /entries this day shape holds/ })).toHaveTextContent(
        "Wake Up",
      ),
    );
  });

  it("shows the habits tab's own table once it is chosen", async () => {
    const strip = await renderTemplates();

    await userEvent.click(within(strip).getByRole("tab", { name: /Habits/ }));

    await waitFor(() => expect(screen.getByRole("table", { name: /^Habits/ })).toBeInTheDocument());
    expect(screen.getByRole("table", { name: /^Habits/ })).toHaveTextContent("4 / wk");
  });

  it("shows the week pattern's seven rows once that tab is chosen", async () => {
    const strip = await renderTemplates();

    await userEvent.click(within(strip).getByRole("tab", { name: "Week pattern" }));

    const table = await screen.findByRole("table", { name: "The declared week pattern" });
    expect(within(table).getAllByRole("row")).toHaveLength(9);
  });

  it("shows the rules and the commitments they type once the anchor types tab is chosen", async () => {
    const strip = await renderTemplates();

    await userEvent.click(within(strip).getByRole("tab", { name: /Anchor types/ }));

    expect(await screen.findByRole("table", { name: /^Anchor types/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /commitments these rules/ })).toHaveTextContent(
      "Kontron Placement Interview",
    );
  });

  /* A first-run tenant reads 404 for the pattern, and the screen has to draw that rather than fail: the tab is
   * the one place a reader can declare the pattern the 404 says is missing. */
  it("draws the week pattern tab when the api answers 404 for the pattern", async () => {
    /* Declared BEFORE the rest, because the first matching handler answers: a later one for the same path is
     * never reached. */
    apiServer.use(
      jsonHandler("/api/v1/week-pattern", {
        status: 404,
        body: {
          type: "syncr:not-found",
          title: "Not found",
          status: 404,
          detail: "No week pattern is declared.",
        },
      }),
      ...screenHandlers(),
    );
    renderAt("/templates");
    const strip = await screen.findByRole("tablist", { name: "Templates" });

    await userEvent.click(within(strip).getByRole("tab", { name: "Week pattern" }));

    const table = await screen.findByRole("table", { name: "The declared week pattern" });
    expect(table).toHaveTextContent("none mapped yet");
  });

  /* The one path only the route can be asked for: a move is computed against the order the rules arrived in,
   * and the whole order is what goes over the wire, because a partial one would move rules the caller cannot
   * see. */
  it("sends the whole evaluation order when a rule is moved", async () => {
    const order = recordingHandler("put", "/api/v1/anchor-types/order", {
      status: 200,
      body: { anchorTypes: [buildLectureType(), buildAnchorType()] },
    });
    apiServer.use(order.handler, ...screenHandlers());
    renderAt("/templates");
    const strip = await screen.findByRole("tablist", { name: "Templates" });

    await userEvent.click(within(strip).getByRole("tab", { name: /Anchor types/ }));
    await userEvent.click(await screen.findByRole("button", { name: "evaluate Lecture earlier" }));

    await waitFor(() =>
      expect(order.bodies).toEqual([{ anchorTypeIds: [TYPE_LECTURE, TYPE_INTERVIEW] }]),
    );
  });

  it("sends the same order when a rule is moved the other way, from the other row", async () => {
    const order = recordingHandler("put", "/api/v1/anchor-types/order", {
      status: 200,
      body: { anchorTypes: [buildLectureType(), buildAnchorType()] },
    });
    apiServer.use(order.handler, ...screenHandlers());
    renderAt("/templates");
    const strip = await screen.findByRole("tablist", { name: "Templates" });

    await userEvent.click(within(strip).getByRole("tab", { name: /Anchor types/ }));
    await userEvent.click(await screen.findByRole("button", { name: "evaluate Interview later" }));

    await waitFor(() =>
      expect(order.bodies).toEqual([{ anchorTypeIds: [TYPE_LECTURE, TYPE_INTERVIEW] }]),
    );
  });
});
