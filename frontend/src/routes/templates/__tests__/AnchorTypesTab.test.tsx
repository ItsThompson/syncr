/* The anchor types tab: the rules in evaluation order, the editor, and the commitments the rules type.
 *
 * Three claims carry this tab. The rules are rendered in the order they evaluate rather than in any order this
 * table chose. A refused edit reaches the reader in amber naming the member to change, which is what makes the
 * prep-lead collision an editing-time fact rather than a solve-time one. And a retyped occurrence reads
 * differently from a rule match, because one survives a rule change and the other does not. */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { AnchorTypesTab } from "../tabs/AnchorTypesTab";
import { withRouter } from "./render";
import { writeDouble } from "./writeDouble";
import {
  AREA_CAREER,
  AREA_FITNESS,
  TYPE_INTERVIEW,
  TYPE_LECTURE,
  buildAnchor,
  buildAnchorType,
  buildAreas,
  buildLectureType,
  buildPrepCollision,
  buildSource,
} from "./fixtures";
import type { AnchorTypeEdit } from "../../../api/hooks/useAnchorTypes";

const types = [buildAnchorType(), buildLectureType()];

function renderTab(overrides: Partial<Parameters<typeof AnchorTypesTab>[0]> = {}) {
  const edit = writeDouble<AnchorTypeEdit>();
  const moves: { readonly direction: string; readonly id: string }[] = [];
  const result = render(
    withRouter(
      <AnchorTypesTab
        types={{ status: "ready", data: types }}
        areas={{ status: "ready", data: buildAreas() }}
        sources={{ status: "ready", data: [buildSource()] }}
        anchors={{ status: "ready", data: { anchors: [buildAnchor()], nextCursor: null } }}
        selectedId={TYPE_INTERVIEW}
        onSelect={() => {}}
        onMoveEarlier={(id) => moves.push({ direction: "earlier", id })}
        onMoveLater={(id) => moves.push({ direction: "later", id })}
        write={edit.write}
        timeZone="UTC"
        {...overrides}
      />,
    ),
  );
  return { edit, moves, ...result };
}

const ruleTable = () => screen.getByRole("table", { name: /^Anchor types/ });
const commitmentTable = () => screen.getByRole("table", { name: /commitments these rules/ });

describe("the rules table", () => {
  it("renders the sheet's six columns in the sheet's order, with the ordering control appended", () => {
    renderTab();

    const headers = within(ruleTable())
      .getAllByRole("columnheader")
      .map((header) => header.textContent);

    expect(headers.slice(0, 6)).toEqual([
      "Type",
      "Match",
      "Pre",
      "Transit",
      "Post",
      "Forbids after",
    ]);
    expect(headers).toHaveLength(7);
  });

  /* The rules arrive in the order they evaluate, and this list is deliberately NOT in alphabetical order: with
   * `Interview` first, a table that sorted its own rows by name would render the same order and the claim would
   * be unfalsifiable. */
  it("renders the rules in the order they evaluate, not in an order it chose", () => {
    renderTab({ types: { status: "ready", data: [buildLectureType(), buildAnchorType()] } });

    const names = within(ruleTable())
      .getAllByRole("row")
      .slice(1, 3)
      .map((row) => within(row).getAllByRole("cell")[0].textContent);

    expect(names).toEqual(["Lecture", "Interview"]);
  });

  it("states each rule's match clause in words rather than identifiers", () => {
    renderTab();

    expect(ruleTable()).toHaveTextContent("title has \u201CInterview\u201D");
    expect(ruleTable()).toHaveTextContent("source = Timetable");
  });

  it("states the prep lead, the outbound journey and the recovery window as figures", () => {
    renderTab();
    const interview = within(ruleTable()).getAllByRole("row")[1];
    const cells = within(interview)
      .getAllByRole("cell")
      .map((cell) => cell.textContent);

    expect(cells.slice(2, 5)).toEqual(["6h", "30m", "1h 15m"]);
  });

  it("names the Areas a recovery window forbids, and the scope when it names none", () => {
    renderTab();

    expect(within(ruleTable()).getByText("Career")).toBeInTheDocument();
    expect(within(ruleTable()).getByText("nothing")).toBeInTheDocument();
  });

  it("states that reordering re-evaluates every existing commitment", () => {
    renderTab();

    expect(
      screen.getByText(/Reordering re-evaluates every existing commitment/),
    ).toBeInTheDocument();
  });
});

describe("reordering the rules", () => {
  it("reports a move to its caller", async () => {
    const { moves } = renderTab();

    await userEvent.click(screen.getByRole("button", { name: "evaluate Lecture earlier" }));

    expect(moves).toEqual([{ direction: "earlier", id: TYPE_LECTURE }]);
  });

  /* A move past either end would send a reorder that reorders nothing while re-evaluating every commitment. */
  it("offers no move earlier on the first rule and none later on the last", () => {
    renderTab();

    expect(screen.getByRole("button", { name: "evaluate Interview earlier" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "evaluate Lecture later" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "evaluate Interview later" })).toBeEnabled();
  });
});

describe("editing a type's geometry", () => {
  it("exposes every member the ticket names", () => {
    renderTab();

    for (const label of [
      "Prep lead",
      "Prep",
      "Prep Area",
      "Transit lead",
      "Transit out",
      "Transit back",
      "Transit Area",
      "Post buffer",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it("reads the recovery scope as the three-way choice, in the reader's words", () => {
    renderTab();

    const scope = screen.getByRole("radiogroup", {
      name: "forbids after: nothing, everything, or these Areas",
    });
    const choices = within(scope)
      .getAllByRole("radio")
      .map((radio) => radio.getAttribute("value"));

    expect(choices).toEqual(["none", "all", "areas"]);
    expect(within(scope).getByRole("radio", { name: "these Areas" })).toBeChecked();
  });

  /* The words are the control: a group named only by an `aria-label` gives a sighted reader no question at all. */
  it("draws the question as well as announcing it", () => {
    renderTab();

    const drawn = screen
      .getAllByText("forbids after: nothing, everything, or these Areas")
      .filter((element) => element.tagName === "P");

    expect(drawn).toHaveLength(1);
  });

  it("submits every geometry member, because each is an absolute value", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies).toEqual([
      {
        prepLeadMinutes: 360,
        prepDurationMinutes: 30,
        prepAreaId: AREA_CAREER,
        transitLeadMinutes: 30,
        transitDurationMinutes: 30,
        returnTransitMinutes: 30,
        transitAreaId: AREA_CAREER,
        postBufferMinutes: 75,
        postScope: "areas",
        forbiddenAreaIds: [AREA_CAREER],
      },
    ]);
  });

  it("carries a stepped prep lead into the body", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getAllByRole("button", { name: "increase 15 minutes" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].prepLeadMinutes).toBe(375);
  });

  /* An Area is what makes a buffer a block: without one the prep generates a forbidden window instead, because
   * a buffer with no Area has no budget to consume. So the null is a real choice and it has to reach the body. */
  it("clears a prep Area to null, which makes prep a forbidden window rather than a block", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: /Prep Area/ }));
    await userEvent.click(
      screen.getByRole("option", { name: /no Area \u00B7 a forbidden window/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].prepAreaId).toBeNull();
  });

  it("names a transit Area, which makes the journey a block in that Area's budget", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: /Transit Area/ }));
    await userEvent.click(screen.getByRole("option", { name: "Fitness" }));
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].transitAreaId).toBe(AREA_FITNESS);
  });

  it("carries a decremented lead into the body, so a step is a real change", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getAllByRole("button", { name: "decrease 15 minutes" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].prepLeadMinutes).toBe(345);
  });

  it("carries a stepped outbound journey and return leg into the body", async () => {
    const { edit } = renderTab();

    /* The rows in order: prep lead, prep, transit lead, transit out, transit back, post buffer. */
    const raise = screen.getAllByRole("button", { name: "increase 15 minutes" });
    await userEvent.click(raise[3]);
    await userEvent.click(raise[4]);
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0]).toMatchObject({
      transitDurationMinutes: 45,
      returnTransitMinutes: 45,
    });
  });

  it("carries a stepped transit lead and post buffer into the body", async () => {
    const { edit } = renderTab();

    const raise = screen.getAllByRole("button", { name: "increase 15 minutes" });
    await userEvent.click(raise[2]);
    await userEvent.click(raise[5]);
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0]).toMatchObject({ transitLeadMinutes: 45, postBufferMinutes: 90 });
  });

  it("adds a forbidden Area as a box rather than as a second select", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("checkbox", { name: "Fitness" }));
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].forbiddenAreaIds).toEqual([AREA_CAREER, AREA_FITNESS]);
  });

  it("removes a forbidden Area that was already named", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("checkbox", { name: "Career" }));

    expect(screen.getByRole("button", { name: "Save the anchor type" })).toBeDisabled();
    expect(edit.bodies).toEqual([]);
  });

  /* The list carries the members of the one scope that has members, and the api holds the two to each other. */
  it("empties the forbidden Areas when the scope stops naming Areas", async () => {
    const { edit } = renderTab();

    await userEvent.click(screen.getByRole("radio", { name: "everything" }));
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies[0].postScope).toBe("all");
    expect(edit.bodies[0].forbiddenAreaIds).toEqual([]);
  });

  it("offers the Area boxes only while the scope names Areas", async () => {
    renderTab();

    expect(screen.getByRole("checkbox", { name: "Career" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("radio", { name: "nothing" }));

    expect(screen.queryByRole("checkbox", { name: "Career" })).not.toBeInTheDocument();
  });

  it("cannot be saved with a scope naming Areas and none named", async () => {
    const { edit } = renderTab({
      types: { status: "ready", data: [buildAnchorType({ forbiddenAreaIds: [] })] },
    });

    expect(screen.getByRole("button", { name: "Save the anchor type" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));

    expect(edit.bodies).toEqual([]);
    expect(screen.getByText(/would forbid nothing/)).toBeInTheDocument();
  });

  /* Null is the abutting default, and there is no figure that means it: the checkbox is the control. */
  it("clears the transit lead to the abutting default, and hides the figure with it", async () => {
    const { edit } = renderTab();

    await userEvent.click(
      screen.getByRole("checkbox", { name: /Leave exactly late enough to arrive on time/ }),
    );

    expect(screen.queryByText("Transit lead")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Save the anchor type" }));
    expect(edit.bodies[0].transitLeadMinutes).toBeNull();
  });

  it("starts a type that already abuts with the box checked and no figure", () => {
    renderTab({ selectedId: TYPE_LECTURE });

    expect(
      screen.getByRole("checkbox", { name: /Leave exactly late enough to arrive on time/ }),
    ).toBeChecked();
    expect(screen.queryByText("Transit lead")).not.toBeInTheDocument();
  });
});

describe("a refused edit", () => {
  it("renders inline in amber, naming which member to change", () => {
    const edit = writeDouble<AnchorTypeEdit>(buildPrepCollision());
    renderTab({ write: edit.write });

    const notice = screen.getByRole("status");
    expect(notice).toHaveTextContent(
      "prepLeadMinutes must be at least 60, which is prepDurationMinutes (30) plus the transit lead (30)",
    );
    expect([...notice.classList]).toContain("notice--amber");
    expect([...notice.classList]).toContain("notice--inline");
  });

  it("puts the same message on the row that owns the member", () => {
    const edit = writeDouble<AnchorTypeEdit>(buildPrepCollision());
    renderTab({ write: edit.write });

    const message = screen.getByText(
      "must be at least 60, which is prepDurationMinutes (30) plus the transit lead (30)",
    );
    expect(message.className).toContain("form-row__message--error");
  });

  it("says what still works, so a refused edit is not read as an outage", () => {
    const edit = writeDouble<AnchorTypeEdit>(buildPrepCollision());
    renderTab({ write: edit.write });

    expect(screen.getByRole("status")).toHaveTextContent("every other anchor type unchanged");
  });
});

describe("the commitments these rules type", () => {
  it("names each commitment's matched type", () => {
    renderTab();

    expect(commitmentTable()).toHaveTextContent("Kontron Placement Interview");
    expect(commitmentTable()).toHaveTextContent("Interview");
  });

  /* A rule match may be replaced by a rule change and a retype may not, so the two cannot read the same. */
  it("distinguishes a retyped occurrence from a rule match", () => {
    renderTab({
      anchors: {
        status: "ready",
        data: {
          anchors: [
            buildAnchor(),
            buildAnchor({
              id: "3f1b7a3c-0015-4c8e-9a11-0000000000n2",
              title: "Standup",
              typeSource: "override",
              seriesUid: "standup-series",
            }),
          ],
          nextCursor: null,
        },
      },
    });

    const rows = within(commitmentTable()).getAllByRole("row").slice(1, 3);
    const provenance = rows.map((row) => within(row).getAllByRole("cell")[3].textContent);

    expect(provenance).toEqual(["rule match", "retyped by you, on the series"]);
    expect(provenance[0]).not.toBe(provenance[1]);
  });

  it("says an unmatched commitment is opaque busy time", () => {
    renderTab({
      anchors: {
        status: "ready",
        data: {
          anchors: [
            buildAnchor({ anchorTypeId: null, anchorTypeName: null, typeSource: "unmatched" }),
          ],
          nextCursor: null,
        },
      },
    });

    expect(commitmentTable()).toHaveTextContent("untyped \u00B7 opaque busy time");
    expect(commitmentTable()).toHaveTextContent("nothing matched");
  });

  it("renders a start in the zone it states, and names that zone", () => {
    renderTab();

    expect(commitmentTable()).toHaveTextContent("09:07");
    expect(commitmentTable()).toHaveTextContent("starts shown in UTC");
  });

  /* The start is not snapped: an imported commitment is a fact and keeps its real time, even at :07. */
  it("keeps a start that does not land on the quarter hour", () => {
    renderTab();

    expect(commitmentTable()).not.toHaveTextContent("09:00");
  });

  it("says so when the span holds more commitments than one page carries", () => {
    renderTab({
      anchors: { status: "ready", data: { anchors: [buildAnchor()], nextCursor: "next" } },
    });

    expect(screen.getByText(/more commitments than one page carries/)).toBeInTheDocument();
  });

  it("says nothing about a further page when this one is the whole span", () => {
    renderTab();

    expect(screen.queryByText(/more commitments than one page carries/)).not.toBeInTheDocument();
  });

  it("says so when no commitment falls in the span", () => {
    renderTab({ anchors: { status: "ready", data: { anchors: [], nextCursor: null } } });

    expect(screen.getByText("No commitment in the next fortnight")).toBeInTheDocument();
  });
});

describe("the tab's three static states", () => {
  it("states what is outstanding while a read is in flight", () => {
    renderTab({ sources: { status: "loading" } });

    expect(screen.getByRole("status")).toHaveTextContent("Reading your anchor types");
  });

  it("names the read that failed", () => {
    renderTab({ anchors: { status: "error", problem: buildPrepCollision() } });

    expect(screen.getByRole("alert")).toHaveTextContent("The commitments could not be read");
  });

  it("says what an untyped commitment means when no type is declared", () => {
    renderTab({ types: { status: "ready", data: [] } });

    expect(screen.getByText("No anchor type is declared")).toBeInTheDocument();
    expect(screen.getByText(/opaque busy time/)).toBeInTheDocument();
  });
});
