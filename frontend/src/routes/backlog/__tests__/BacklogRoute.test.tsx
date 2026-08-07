/* THE BACKLOG AS A READER MEETS IT: the band's two figures, the table, the three row treatments, and the four
 * surfaces the screen draws when there is nothing to draw.
 *
 * WHAT THE CAPTURE FLOW DOES IS THE OTHER FILE. This one is about the reading, the ordering and the completion. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";

import { apiServer } from "../../../testing/apiServer";
import { pendingHandler, unreachableHandler } from "../../../testing/apiStub";
import { renderSignedInAt } from "../../../testing/renderRoute";
import {
  AREA_FITNESS,
  NOW_MS,
  TASK_AT_RISK,
  TASK_ORDINARY,
  TASK_OVERDUE,
  TOMORROW,
  YESTERDAY,
  buildBacklog,
  buildHeader,
  buildProblem,
  buildTask,
  buildThreeTreatments,
} from "./fixtures";
import { renderBacklog, stubBacklog } from "./render";

const origin = window.location.origin;

/** The row holding a title, found by the cell the Task column drew. */
function rowOf(title: string): HTMLElement {
  const row = screen.getByText(title, { selector: ".table__cell" }).closest("tr");
  if (row === null) throw new Error(`${title} is in no row`);
  return row;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("the page and its band", () => {
  it("renders a serif page title and a table of tasks with a footer count", async () => {
    await renderBacklog({ backlog: buildThreeTreatments() });

    const title = await screen.findByRole("heading", { level: 1, name: "Backlog" });
    expect(title).toHaveClass("font-serif");
    expect(screen.getByRole("table", { name: "The backlog" })).toBeInTheDocument();
    expect(screen.getByText("3 rows")).toBeInTheDocument();
  });

  /* Both figures are read from the response's header rather than counted from the rows, which is what a
     one-row page proves: a band counting its own rows would say 1 and 0. */
  it("states the count of open tasks and the count at risk from the server, not from the page", async () => {
    await renderBacklog({
      backlog: buildBacklog({
        header: buildHeader({ openCount: 9, atRiskCount: 4 }),
        tasks: [buildTask()],
      }),
    });

    expect((await screen.findByText("open tasks")).parentElement).toHaveTextContent("9");
    expect(
      screen.getByText("at risk", { selector: ".stat-cell__label" }).parentElement,
    ).toHaveTextContent("4");
    expect(screen.getByText("1 row")).toBeInTheDocument();
  });

  it("advertises the global capture keystroke beside the control that opens it", async () => {
    await renderBacklog();

    expect(await screen.findByRole("button", { name: "Capture a task" })).toBeInTheDocument();
    expect(screen.getByText("n", { selector: "kbd" })).toBeInTheDocument();
  });
});

describe("the three row treatments", () => {
  /* THE DETERMINATION IS THE SERVER'S AND THE SCREEN COMPUTES NO COMPARISON. Both deadlined rows here are due
     inside the same week and both carry work; what separates them is the field the api sent. A screen that
     compared a deadline against a capacity of its own could not tell them apart. */
  it("marks the row the response marks, and does not mark a deadlined row it does not", async () => {
    await renderBacklog({
      backlog: buildBacklog({
        header: buildHeader({ openCount: 2, atRiskCount: 1 }),
        tasks: [
          buildTask({
            id: TASK_AT_RISK,
            title: "Kontron take-home",
            deadline: TOMORROW,
            atRisk: true,
          }),
          buildTask({ title: "Read one paper", deadline: TOMORROW, atRisk: false }),
        ],
      }),
    });

    await screen.findByRole("table", { name: "The backlog" });
    expect(rowOf("Kontron take-home")).toHaveAttribute("data-at-risk");
    expect(rowOf("Read one paper")).not.toHaveAttribute("data-at-risk");
  });

  it("tells an overdue row, an at-risk row and an ordinary one apart, and says which in words", async () => {
    vi.setSystemTime(NOW_MS);
    await renderBacklog({ backlog: buildThreeTreatments() });
    await screen.findByRole("table", { name: "The backlog" });

    const ordinary = rowOf("Read one paper");
    const atRisk = rowOf("Kontron take-home");
    const overdue = rowOf("Renew the visa");

    expect(ordinary).not.toHaveAttribute("data-at-risk");
    expect(ordinary).not.toHaveAttribute("data-overdue");
    expect(atRisk).toHaveAttribute("data-at-risk");
    expect(atRisk).not.toHaveAttribute("data-overdue");
    expect(overdue).toHaveAttribute("data-overdue");
    /* Both, and the fixture is the api's own answer for it: capacity is clipped to now, so a passed deadline
       with work left has none before it and the verdict names it too. */
    expect(overdue).toHaveAttribute("data-at-risk");

    expect(within(atRisk).getByText("at risk")).toBeInTheDocument();
    expect(within(overdue).getByText("overdue and at risk")).toBeInTheDocument();
  });

  it("draws no standing on a row that has left the backlog, because nothing is owed on it", async () => {
    vi.setSystemTime(NOW_MS);
    await renderBacklog({
      backlog: buildBacklog({
        tasks: [
          buildTask({
            title: "Renew the visa",
            deadline: YESTERDAY,
            status: "completed",
            completedAt: YESTERDAY,
            atRisk: false,
          }),
        ],
      }),
    });

    await screen.findByRole("table", { name: "The backlog" });
    expect(rowOf("Renew the visa")).not.toHaveAttribute("data-overdue");
  });
});

describe("sorting and filtering", () => {
  /* THE FILTER IS THE QUERY. Choosing an Area has to reach the api, because the at-risk narrowing is the
     server's determination and a screen that narrowed a list it already held would show a count and a row set
     that disagree. */
  it("changes the query when a filter changes, and opens on the open tasks", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    expect(stub.queries).toEqual(["status=open"]);

    await userEvent.click(screen.getByRole("combobox", { name: "Standing" }));
    await userEvent.click(screen.getByRole("option", { name: "At risk" }));

    await waitFor(() => {
      expect(stub.queries.at(-1)).toBe("status=open&atRisk=true");
    });
  });

  it("sends the Area filter the api's own parameter name", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });

    await userEvent.click(screen.getByRole("combobox", { name: "Area" }));
    await userEvent.click(screen.getByRole("option", { name: "Fitness" }));

    await waitFor(() => {
      expect(stub.queries.at(-1)).toBe(`areaId=${AREA_FITNESS}&status=open`);
    });
  });

  /* SORTING CHANGES THE ORDER THE ROWS ARRIVE IN AND NOTHING ELSE. `GET /api/v1/tasks` serves the backlog
     oldest first and states that the read order is the screen's decision, so a sort must not become a request:
     a second read would cost a whole week assembly to reorder rows the client already holds. */
  it("reorders the rows without reading again", async () => {
    const stub = await renderBacklog({ backlog: buildThreeTreatments() });
    await screen.findByRole("table", { name: "The backlog" });
    const before = stub.queries.length;

    await userEvent.click(screen.getByRole("button", { name: /Task/ }));

    const titles = screen
      .getAllByRole("row")
      .slice(1, 4)
      .map((row) => row.querySelectorAll(".table__cell")[1]?.textContent);
    expect(titles).toEqual(["Kontron take-home", "Read one paper", "Renew the visa"]);
    expect(stub.queries).toHaveLength(before);
  });

  it("announces the order on the column the rows actually run by", async () => {
    await renderBacklog({ backlog: buildThreeTreatments() });
    await screen.findByRole("table", { name: "The backlog" });

    expect(screen.getByRole("columnheader", { name: /Deadline/ })).toHaveAttribute(
      "aria-sort",
      "ascending",
    );
    expect(screen.getByRole("columnheader", { name: /Task/ })).toHaveAttribute("aria-sort", "none");
  });
});

describe("completing a task from the table", () => {
  it("removes it from the list and states what happens to the blocks planned for it", async () => {
    const stub = await renderBacklog({ backlog: buildThreeTreatments() });
    await screen.findByRole("table", { name: "The backlog" });
    /* The list the next read answers with is the api's own answer for a completed task under `status=open`:
       the row is gone and the header is one lighter. */
    stub.answerWith({
      header: buildHeader({ openCount: 2, atRiskCount: 1 }),
      tasks: [
        buildTask({
          id: TASK_AT_RISK,
          title: "Kontron take-home",
          deadline: TOMORROW,
          atRisk: true,
        }),
        buildTask({ id: TASK_OVERDUE, title: "Renew the visa", deadline: YESTERDAY, atRisk: true }),
      ],
    });

    await userEvent.click(
      within(rowOf("Read one paper")).getByRole("button", { name: "Complete" }),
    );

    await waitFor(() => {
      expect(screen.queryByText("Read one paper")).not.toBeInTheDocument();
    });
    expect(stub.completed).toEqual([TASK_ORDINARY]);
    const notice = screen.getByRole("status", { name: "Task completed" });
    expect(notice).toHaveTextContent("become empty space in the next solve");
    expect(notice).toHaveTextContent("applies without being approved");
  });

  it("keeps the row and says why when the api refuses the completion", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    stub.refuseCompletionWith(
      409,
      buildProblem({
        type: "syncr:conflict",
        title: "This task is already dropped",
        status: 409,
        detail: "A dropped task cannot be completed.",
      }),
    );

    await userEvent.click(screen.getByRole("button", { name: "Complete" }));

    const notice = await screen.findByRole("status", { name: "This task is already dropped" });
    expect(notice).toHaveTextContent("A dropped task cannot be completed.");
    expect(screen.getByText("Read one paper")).toBeInTheDocument();
  });
});

describe("the at-risk marking's currency", () => {
  /* NOTHING PUSHES IT AND NOTHING POLLS FOR IT. `US-TASK-03` says the determination is recomputed on every read
     rather than on a timer, and the event union carries no verdict member. So the only thing that makes this
     screen read again is a write on it: the mark that moved below is the api's own answer to the read the
     completion invalidated. */
  it("reads the new marking after a write, without a timer of its own", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.setSystemTime(NOW_MS);
    const stub = await renderBacklog({ backlog: buildThreeTreatments() });
    await screen.findByRole("table", { name: "The backlog" });
    const reads = stub.queries.length;
    /* Asserted before as well as after, so the figure is seen to MOVE: a band that stated a constant would
       satisfy the assertion below on its own. */
    expect(
      screen.getByText("at risk", { selector: ".stat-cell__label" }).parentElement,
    ).toHaveTextContent("2");

    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    expect(stub.queries).toHaveLength(reads);

    stub.answerWith({
      header: buildHeader({ openCount: 2, atRiskCount: 0 }),
      tasks: [
        buildTask({
          id: TASK_AT_RISK,
          title: "Kontron take-home",
          deadline: TOMORROW,
          atRisk: false,
        }),
        buildTask({
          id: TASK_OVERDUE,
          title: "Renew the visa",
          deadline: YESTERDAY,
          atRisk: false,
        }),
      ],
    });
    await userEvent.click(
      within(rowOf("Read one paper")).getByRole("button", { name: "Complete" }),
    );

    await waitFor(() => {
      expect(rowOf("Kontron take-home")).not.toHaveAttribute("data-at-risk");
    });
    expect(
      screen.getByText("at risk", { selector: ".stat-cell__label" }).parentElement,
    ).toHaveTextContent("0");
  });
});

describe("the states with nothing to show", () => {
  it("says what it is waiting for, in words, while the read is in flight", async () => {
    apiServer.use(
      pendingHandler("/api/v1/tasks"),
      http.get(`${origin}/api/v1/areas`, () => HttpResponse.json({ areas: [], ramp: null })),
    );
    await renderSignedInAt("/backlog");

    const pending = (await screen.findByText("Reading the backlog")).closest(".status");
    expect(pending).toHaveAttribute("role", "status");
    expect(pending).toHaveTextContent("which of them this week's verdict names");
    expect(pending?.querySelector("[class*=spin]")).toBeNull();
  });

  it("names the read that failed and says what it said", async () => {
    const stub = stubBacklog();
    apiServer.use(unreachableHandler("/api/v1/tasks"));
    await renderSignedInAt("/backlog");
    expect(stub.queries).toEqual([]);

    const failed = await screen.findByRole("alert");
    expect(failed).toHaveTextContent("The backlog could not be read");
  });

  it("carries a capture prompt when the list is empty", async () => {
    await renderBacklog({
      backlog: { header: buildHeader({ openCount: 0, atRiskCount: 0 }), tasks: [] },
    });

    expect(await screen.findByText("No task is in this list")).toBeInTheDocument();
    expect(screen.getByText(/press n from any screen/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture the first one" })).toBeInTheDocument();
  });
});
