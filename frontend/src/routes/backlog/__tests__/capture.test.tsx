/* THE CAPTURE FLOW: `n` from any screen, the request body, the boundary rejection, and the focus that returns.
 *
 * THE KEYSTROKE IS DRIVEN ON A SCREEN THAT IS NOT THE BACKLOG, because that is the claim: capture must never
 * compete with the thing being captured, so a test that only opened it from `/backlog` would prove nothing about
 * the one property the binding exists for.
 *
 * THE REQUEST BODY IS ASSERTED WHOLE. A form's contract is what it sends, and the two-value capture is only true
 * if every other member arrives with a default the api documents. Asserting the members one at a time would let a
 * missing one pass.
 *
 * FOCUS RETURN IS RADIX'S AND IS ASSERTED RATHER THAN TRUSTED. The dialog's focus scope restores the element that
 * was focused before it opened; what a test can say is that the reader is back where they were, which is the
 * promise, and it holds for the submit path and the dismiss path through one mechanism. */

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { renderSignedInAt } from "../../../testing/renderRoute";
import {
  AREA_CAREER,
  AREA_FITNESS,
  buildBacklog,
  buildHeader,
  buildProblem,
  buildTask,
} from "./fixtures";
import { renderBacklog, stubBacklog } from "./render";

const CAPTURE = "Capture a task";

/** Opening capture with the global keystroke, from wherever the reader is. */
async function pressN(): Promise<void> {
  await userEvent.keyboard("n");
  await screen.findByRole("dialog", { name: CAPTURE });
}

async function fillTitle(title: string): Promise<void> {
  await userEvent.type(screen.getByRole("textbox", { name: /Task/ }), title);
}

async function chooseArea(name: string): Promise<void> {
  await userEvent.click(screen.getByRole("combobox", { name: /Area/ }));
  await userEvent.click(screen.getByRole("option", { name }));
}

describe("opening capture", () => {
  it("opens from a screen that is not the backlog, which is the whole point of the binding", async () => {
    const stub = stubBacklog();
    await renderSignedInAt("/areas");

    await pressN();

    expect(screen.getByRole("dialog", { name: CAPTURE })).toBeInTheDocument();
    /* The backlog has not been read at all: the dialog is the shell's, not the screen's. */
    expect(stub.queries).toEqual([]);
  });

  it("does not open while the reader is typing into a field", async () => {
    await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });

    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("note");

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: /Task/ })).toHaveValue("note");
  });

  it("keeps a draft in flight when the keystroke is pressed again", async () => {
    await renderSignedInAt("/areas");
    await pressN();
    await fillTitle("half typed");

    await userEvent.keyboard("{Escape}");
    await pressN();

    expect(screen.getByRole("textbox", { name: /Task/ })).toHaveValue("");
  });
});

describe("what the form requires", () => {
  it("sends a title, an Area, and a documented default for everything else", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));

    await fillTitle("Kontron take-home");
    await chooseArea("Career");
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(stub.captured).toEqual([
        {
          areaId: AREA_CAREER,
          title: "Kontron take-home",
          estimateMinutes: 30,
          minChunkMinutes: 15,
          deadline: null,
          priority: "normal",
          splittable: true,
        },
      ]);
    });
  });

  it("refuses to submit until both required values are there", async () => {
    stubBacklog();
    await renderSignedInAt("/areas");
    await pressN();
    const submit = screen.getByRole("button", { name: "Capture" });

    expect(submit).toBeDisabled();
    await fillTitle("Kontron take-home");
    expect(submit).toBeDisabled();
    await chooseArea("Career");
    expect(submit).toBeEnabled();
  });

  it("refuses a title of nothing but spaces rather than trimming it into one", async () => {
    stubBacklog();
    await renderSignedInAt("/areas");
    await pressN();

    await fillTitle("   ");
    await chooseArea("Career");

    expect(screen.getByRole("button", { name: "Capture" })).toBeDisabled();
    expect(screen.getByText("A task needs a title.")).toBeInTheDocument();
  });

  it("trims a title that has words in it, because trailing space is not a word", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));

    await fillTitle("  Kontron take-home  ");
    await chooseArea("Fitness");
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(stub.captured).toHaveLength(1);
    });
    expect(stub.captured[0]).toMatchObject({
      title: "Kontron take-home",
      areaId: AREA_FITNESS,
    });
  });
});

describe("the fields the form exposes", () => {
  it("exposes the estimate, an optional deadline, the priority, the minimum chunk and splittable", async () => {
    stubBacklog();
    await renderSignedInAt("/areas");
    await pressN();
    const dialog = screen.getByRole("dialog", { name: CAPTURE });

    expect(within(dialog).getByRole("spinbutton", { name: /Estimate/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("textbox", { name: /Deadline/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: /Priority/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("spinbutton", { name: /Minimum chunk/ })).toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: /divide this/ })).toBeInTheDocument();
  });

  /* THE ONE FIELD THAT MUST NOT BE HERE. A preferred time is a `Preference` whose owner is an Area, so a task
     inherits its Area's windows unless it overrides them, and the api's request shape refuses the member
     outright. The hint is what tells a reader where to author one instead. */
  it("has no preferred-time field, and says where preferred times are authored", async () => {
    stubBacklog();
    await renderSignedInAt("/areas");
    await pressN();
    const dialog = screen.getByRole("dialog", { name: CAPTURE });

    /* The words appear in a HINT and never as a label, which is the whole distinction: a reader is told where
       preferred times live and is offered no control for one here. */
    expect(within(dialog).getByText(/no preferred time here/i)).toHaveTextContent(
      "Preference column on the Areas screen",
    );
    for (const label of [/preferred/i, /window/i, /time of day/i]) {
      expect(within(dialog).queryByRole("textbox", { name: label })).toBeNull();
      expect(within(dialog).queryByRole("spinbutton", { name: label })).toBeNull();
      expect(within(dialog).queryByRole("combobox", { name: label })).toBeNull();
      expect(within(dialog).queryByLabelText(label)).toBeNull();
    }
  });
});

describe("the minimum chunk against the estimate", () => {
  /* T1 IS THE DOMAIN'S AND THIS IS AN AFFORDANCE. What the form does is stop a submit the domain would refuse,
     so the reader is told at the field instead of after a round trip; the rule itself has one statement, in
     `syncr_domain.tasks`, and its own sentence lands on this row through the same prop whenever the api answers
     with it. */
  it("states the rejection at the field and will not submit while it stands", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("Kontron take-home");
    await chooseArea("Career");

    const chunk = screen.getByRole("spinbutton", { name: /Minimum chunk/ });
    await userEvent.clear(chunk);
    await userEvent.type(chunk, "60");
    await userEvent.tab();

    expect(screen.getByText(/no placement could satisfy both/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Capture" })).toBeDisabled();
    expect(stub.captured).toEqual([]);
  });

  it("submits once the pair fits again", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("Kontron take-home");
    await chooseArea("Career");
    const estimate = screen.getByRole("spinbutton", { name: /Estimate/ });
    const chunk = screen.getByRole("spinbutton", { name: /Minimum chunk/ });
    await userEvent.clear(chunk);
    await userEvent.type(chunk, "60");
    await userEvent.tab();

    await userEvent.clear(estimate);
    await userEvent.type(estimate, "120");
    await userEvent.tab();
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(stub.captured).toHaveLength(1);
    });
    expect(stub.captured[0]).toMatchObject({ estimateMinutes: 120, minChunkMinutes: 60 });
  });
});

describe("a refusal the api answers with", () => {
  /* THE FIELD THE BOUNDARY NAMES IS THE FIELD THE MESSAGE LANDS ON, and the field driven here is one the form
     does NOT guard: the Area the reader chose no longer exists. A test driving the minimum chunk instead would
     prove a case the wiring cannot produce, because the submit is disabled while that pair is out of bounds. */
  it("puts a field error on the row the api named, and keeps the draft", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    stub.refuseCaptureWith(
      422,
      buildProblem({
        detail: "One or more members were refused.",
        errors: [{ field: "areaId", message: "names no Area of this tenant" }],
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("Kontron take-home");
    await chooseArea("Career");

    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    expect(await screen.findByText("names no Area of this tenant")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Task/ })).toHaveValue("Kontron take-home");
    expect(screen.getByRole("dialog", { name: CAPTURE })).toBeInTheDocument();
  });

  it("names a member the form has no row for in the refusal's own sentence", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    stub.refuseCaptureWith(
      422,
      buildProblem({
        detail: "One or more members were refused.",
        errors: [{ field: "projectId", message: "belongs to another Area" }],
      }),
    );
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("Kontron take-home");
    await chooseArea("Career");

    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    const notice = await screen.findByRole("status", { name: "Validation failed" });
    expect(notice).toHaveTextContent("projectId belongs to another Area.");
  });

  it("says a request that never arrived never arrived, and keeps the draft", async () => {
    const stub = await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    stub.refuseCaptureWith(503, buildProblem({ title: "Service unavailable", status: 503 }));
    await userEvent.click(screen.getByRole("button", { name: CAPTURE }));
    await fillTitle("Kontron take-home");
    await chooseArea("Career");

    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    expect(await screen.findByRole("status", { name: "Service unavailable" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /Task/ })).toHaveValue("Kontron take-home");
  });
});

describe("where the reader ends up", () => {
  it("returns focus to the control the reader was on when they submitted", async () => {
    const stub = await renderBacklog({ backlog: buildBacklog() });
    await screen.findByRole("table", { name: "The backlog" });
    const sortHeader = screen.getByRole("button", { name: /Task/ });
    sortHeader.focus();
    expect(sortHeader).toHaveFocus();

    await pressN();
    await fillTitle("Kontron take-home");
    await chooseArea("Career");
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: CAPTURE })).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(sortHeader).toHaveFocus();
    });
    expect(stub.captured).toHaveLength(1);
  });

  it("returns focus when the reader dismisses instead of submitting", async () => {
    await renderBacklog();
    await screen.findByRole("table", { name: "The backlog" });
    const capture = screen.getByRole("button", { name: CAPTURE });
    capture.focus();

    await pressN();
    await userEvent.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: CAPTURE })).not.toBeInTheDocument();
    });
    await waitFor(() => {
      expect(capture).toHaveFocus();
    });
  });

  it("shows the captured task once the list has been read again", async () => {
    const stub = await renderBacklog({
      backlog: { header: buildHeader({ openCount: 0, atRiskCount: 0 }), tasks: [] },
    });
    await screen.findByText("No task is in this list");
    stub.answerWith(buildBacklog({ tasks: [buildTask({ title: "Kontron take-home" })] }));

    await pressN();
    await fillTitle("Kontron take-home");
    await chooseArea("Career");
    await userEvent.click(screen.getByRole("button", { name: "Capture" }));

    expect(
      await screen.findByText("Kontron take-home", { selector: ".table__cell" }),
    ).toBeInTheDocument();
  });
});
