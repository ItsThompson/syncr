/* THE THREE VOLUMES, AND THE FOURTH THAT DOES NOT EXIST.
 *
 * Volume is position and pigment is kind, so the cases below are about WHERE a notice sits and WHAT it says,
 * never about how loud its colour is. Two claims here are enforced by something other than a rendering: the
 * required surviving-capability field is a type rule the typecheck refuses to break, and the absence of a
 * blocking volume is asserted over the barrel rather than trusted to a comment. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import * as notices from "..";
import { componentNamesIn } from "../../../../testing/kitExports";
import { NoticeCard } from "../NoticeCard";
import { NoticePanel } from "../NoticePanel";
import { NoticeStrip } from "../NoticeStrip";
import { noticeFrom, outageFrom } from "../notice";
import type { Notice, NoticeAction, NoticePigment, NoticeVolume, WireNotice } from "../notice";

/* The base is a real `Notice` rather than a cast, and the overrides are the fields these cases vary. A factory
 * typed `Partial<Notice>` would need a cast to spread over a union, and a cast is exactly what would hide the
 * type rule this file is here to pin. */
const BASE_NOTICE: Notice = {
  id: "write-target-expired",
  volume: "banner",
  pigment: "oxide",
  title: "Write target rejected the write",
  detail: "The Google refresh token for syncr · plan expired. 91 blocks are unwritten.",
  unavailable: ["writing the plan to your calendar"],
  stillWorks: ["reading and editing the plan", "solving the week"],
  since: "2026-08-02T04:12:00Z",
  action: { label: "Reconnect", href: "/settings" },
  scope: { screen: "/settings" },
};

interface NoticeOverrides {
  readonly volume?: NoticeVolume;
  readonly pigment?: NoticePigment;
  readonly action?: NoticeAction | null;
  readonly since?: string | null;
}

function buildNotice(overrides: NoticeOverrides = {}): Notice {
  return { ...BASE_NOTICE, ...overrides };
}

describe("what still works", () => {
  it("is stated at the panel volume, one capability to a row", () => {
    render(<NoticePanel notice={buildNotice({ volume: "panel" })} />);

    expect(screen.getByText("still works · reading and editing the plan")).toBeInTheDocument();
    expect(screen.getByText("still works · solving the week")).toBeInTheDocument();
    expect(screen.getByText("unavailable · writing the plan to your calendar")).toBeInTheDocument();
  });

  it("is stated at the inline volume too, joined into the one line it has room for", () => {
    render(<NoticeCard notice={buildNotice({ volume: "inline" })} />);

    expect(
      screen.getByText("still works · reading and editing the plan, solving the week"),
    ).toBeInTheDocument();
  });

  it("is stated in the top bar, where a reader sees it until the condition clears", () => {
    render(<NoticeStrip notice={buildNotice()} />);

    expect(screen.getByText(/still works ·/)).toBeInTheDocument();
  });

  /* THE TYPE IS THE ENFORCEMENT, NOT A CONVENTION. Every degradation notice has to name the capability that
   * survives, because one that says only what broke leaves a reader unable to decide what to do next. These two
   * cases are checked by `tsc --noEmit`, which runs over `src`: a `@ts-expect-error` that stops erroring fails
   * the typecheck, so the rule cannot be quietly relaxed. */
  it("cannot be omitted", () => {
    const { stillWorks, ...withoutSurvival } = BASE_NOTICE;

    // @ts-expect-error a notice that says only what broke is not a notice this product renders
    const notice: Notice = withoutSurvival;

    expect(notice).toBeDefined();
    expect(stillWorks.length).toBeGreaterThan(0);
  });

  it("cannot be empty unless the whole product is down", () => {
    const outage: Notice = { ...BASE_NOTICE, stillWorks: [], isWholeProductDown: true };

    // @ts-expect-error an empty list is legal only on the arm that declares a total outage
    const empty: Notice = { ...BASE_NOTICE, stillWorks: [] };

    expect(empty).toBeDefined();
    expect(outage.stillWorks).toHaveLength(0);
  });

  it("says so in words when the whole product is down, rather than leaving the line blank", () => {
    render(<NoticePanel notice={outageFrom({ ...BASE_NOTICE, volume: "panel" })} />);

    expect(
      screen.getByText("nothing is available while the whole product is down"),
    ).toBeInTheDocument();
  });
});

/* THE BOUNDARY, WHICH IS WHAT KEEPS THE TYPE RULE FROM BEING CAST AWAY. The api types `stillWorks` as a plain
 * array, so a response is not assignable to `Notice` and the cheapest way out would be `as Notice`: precisely the
 * escape the non-empty tuple exists to close. `noticeFrom` is the narrowing, and it lives in the file that owns the
 * invariant. */
describe("a notice arriving over the wire", () => {
  const wire: WireNotice = { ...BASE_NOTICE, stillWorks: ["reading the plan"] };

  it("narrows to the kit's type when it names a surviving capability", () => {
    const narrowed = noticeFrom(wire);

    expect(narrowed?.stillWorks).toEqual(["reading the plan"]);
  });

  it("is refused when it names none, rather than being cast into the kit", () => {
    expect(noticeFrom({ ...wire, stillWorks: [] })).toBeNull();
  });

  it("renders through the narrowing without a cast at the call site", () => {
    const narrowed = noticeFrom({ ...wire, volume: "panel" });
    if (narrowed === null) throw new Error("the fixture names a surviving capability");

    render(<NoticePanel notice={narrowed} />);

    expect(screen.getByText("still works \u00b7 reading the plan")).toBeInTheDocument();
  });

  it("declares a total outage at a call site rather than inferring one from an empty array", () => {
    const outage = outageFrom({ ...wire, stillWorks: [] });

    expect(outage.isWholeProductDown).toBe(true);
    expect(outage.stillWorks).toHaveLength(0);
  });

  /* THE DOCUMENT LEAVES FOUR FIELDS OUT RATHER THAN SENDING THEM EMPTY. A notice about no one thing carries no
   * scope, one with no repair carries no action, and one whose age is unknown carries no instant. The kit's type
   * has no absent case for any of them, so the narrowing is where an omission becomes the empty reading. */
  it("reads an omitted list, instant, action and scope as the kit's own absences", () => {
    const sparse = noticeFrom({
      id: "calendar.feed-stale",
      volume: "panel",
      pigment: "amber",
      title: "Timetable could not be read",
      detail: "The feed answered 503.",
      stillWorks: ["the anchors it already contributed"],
    });

    expect(sparse?.unavailable).toEqual([]);
    expect(sparse?.since).toBeNull();
    expect(sparse?.action).toBeNull();
    expect(sparse?.scope).toBeNull();
  });

  it("reads a scope member sent as null as absent, which is what the kit's scope means by it", () => {
    const scoped = noticeFrom({
      ...wire,
      scope: { screen: "settings", blockId: null, sourceId: null, date: null },
    });

    expect(scoped?.scope).toEqual({
      screen: "settings",
      blockId: undefined,
      sourceId: undefined,
      date: undefined,
    });
  });

  it("carries the omissions through the outage form too, so one shape is not looser than the other", () => {
    const outage = outageFrom({
      id: "whole-product",
      volume: "banner",
      pigment: "oxide",
      title: "syncr is unavailable",
      detail: "The api cannot be reached.",
      stillWorks: [],
    });

    expect(outage.unavailable).toEqual([]);
    expect(outage.since).toBeNull();
    expect(outage.action).toBeNull();
    expect(outage.scope).toBeNull();
  });

  /* The wire type is what the response actually is, so this pins that the narrowing is the only way in: a plain
   * array assigned straight to `Notice` is the error the guard exists to answer. */
  it("does not assign straight to the kit's type", () => {
    // @ts-expect-error a plain array is not a non-empty tuple: narrow it with noticeFrom
    const direct: Notice = wire;

    expect(direct).toBeDefined();
  });
});

/* ONE CONDITION, TWO VOLUMES. The api raises the write target's expiry twice, as a banner and as a panel with a
 * shared identity root, because a notice carries one volume. Two surfaces each ask for their own. */
describe("selecting the notices for one volume", () => {
  const banner: WireNotice = {
    ...BASE_NOTICE,
    id: "google.write-target-expired.banner",
    stillWorks: ["reading your calendars"],
  };
  const panel: WireNotice = { ...banner, id: "google.write-target-expired.panel", volume: "panel" };

  it("answers with the ones at that volume and no others", () => {
    expect(notices.noticesAt("banner", [banner, panel]).map((one) => one.id)).toEqual([
      "google.write-target-expired.banner",
    ]);
    expect(notices.noticesAt("panel", [banner, panel]).map((one) => one.id)).toEqual([
      "google.write-target-expired.panel",
    ]);
  });

  it("narrows each one, so a call site renders without a cast", () => {
    const [only] = notices.noticesAt("panel", [panel]);
    if (only === undefined) throw new Error("the fixture is at panel volume");

    render(<NoticePanel notice={only} />);

    expect(screen.getByText("still works \u00b7 reading your calendars")).toBeInTheDocument();
  });

  it("drops one that names no surviving capability rather than rendering it", () => {
    expect(notices.noticesAt("banner", [{ ...banner, stillWorks: [] }])).toEqual([]);
  });

  it("answers with nothing when the response carries none", () => {
    expect(notices.noticesAt("banner", [])).toEqual([]);
  });
});

describe("the pigment", () => {
  it.each([
    ["info", "notice--info", "glyph--notice-info"],
    ["amber", "notice--amber", "glyph--notice-attention"],
    ["oxide", "notice--oxide", "glyph--cross"],
    ["verdigris", "notice--verdigris", "glyph--check"],
  ] as const)("gives %s its own class and its own mark", (pigment, surface, mark) => {
    const { container } = render(
      <NoticePanel notice={buildNotice({ volume: "panel", pigment })} />,
    );

    expect(container.firstElementChild).toHaveClass(surface);
    expect(container.querySelector(".notice__mark")).toHaveClass(mark);
  });

  it("hides the mark from a screen reader, because the title says the kind in words", () => {
    const { container } = render(<NoticePanel notice={buildNotice({ volume: "panel" })} />);

    expect(container.querySelector(".notice__mark")).toHaveAttribute("aria-hidden", "true");
  });

  /* A failure interrupts and nothing else does. Derived from the pigment, so the announced urgency and the drawn
   * one cannot disagree. */
  it("makes a failure an alert and every other kind a status", () => {
    render(<NoticePanel notice={buildNotice({ volume: "panel", pigment: "oxide" })} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();

    render(<NoticePanel notice={buildNotice({ volume: "panel", pigment: "amber" })} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

describe("the action", () => {
  it("is a real link with an href, because a repair is as often external as internal", () => {
    render(<NoticePanel notice={buildNotice({ volume: "panel" })} />);

    expect(screen.getByRole("link", { name: "Reconnect" })).toHaveAttribute("href", "/settings");
  });

  it("is absent from the inline volume, where the row it sits on is the repair", () => {
    render(<NoticeCard notice={buildNotice({ volume: "inline" })} />);

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("is offered in the top bar, with a dismissal only where acknowledging is the resolution", async () => {
    const onDismiss = vi.fn<() => void>();
    render(<NoticeStrip notice={buildNotice()} onDismiss={onDismiss} />);

    screen.getByRole("button", { name: "Dismiss this notice" }).click();

    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("leaves the banner undismissable without one, because a notice nobody fixed should stay", () => {
    render(<NoticeStrip notice={buildNotice()} />);

    expect(screen.queryByRole("button", { name: "Dismiss this notice" })).toBeNull();
  });
});

describe("how long the condition has held", () => {
  it("is rendered through the caller's own formatter, in the reader's zone", () => {
    render(
      <NoticePanel
        notice={buildNotice({ volume: "panel" })}
        formatSince={() => "Sunday at 04:12"}
      />,
    );

    expect(screen.getByText("since Sunday at 04:12")).toBeInTheDocument();
  });

  it("is absent without one, rather than reading an ISO instant aloud", () => {
    render(<NoticePanel notice={buildNotice({ volume: "panel" })} />);

    expect(screen.queryByText(/since/)).toBeNull();
  });
});

/* LEVEL 4 IS DELIBERATELY UNUSED. syncr does not stop a reader approving a knowingly broken week: infeasibility
 * is the product's most valuable output, and a week that cannot hold its commitments is impossible rather than
 * broken. The barrel is what this asserts against, so a fourth volume cannot arrive as a component nobody
 * reviewed. */
describe("the blocking volume", () => {
  it("does not exist: the barrel exports three volumes and their mark", () => {
    expect(componentNamesIn(notices)).toEqual([
      "NoticeCard",
      "NoticeMark",
      "NoticePanel",
      "NoticeStrip",
    ]);
  });

  it("is not reachable under another name either", () => {
    const names = componentNamesIn(notices).join(" ").toLowerCase();

    expect(names).not.toContain("dialog");
    expect(names).not.toContain("modal");
    expect(names).not.toContain("toast");
  });
});
