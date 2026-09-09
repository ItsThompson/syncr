import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DayMarkSlot, dayHeaderMarkOf } from "../DayMarkSlot";
import type { DayMark } from "../types";
import type { Notice } from "../../notices";

const NOTICE: Notice = {
  id: "stale-calendar-source",
  volume: "inline",
  pigment: "amber",
  title: "A calendar source could not be read",
  detail: "Imported commitments on this day may be out of date.",
  unavailable: ["reading new commitments from this calendar source"],
  stillWorks: ["the plan on the grid"],
  since: null,
  action: null,
  scope: { screen: "/week", date: "2026-02-09" },
};

function mark(pigment: DayMark["pigment"]): DayMark {
  return { pigment, notice: { ...NOTICE, pigment } };
}

describe("the day header mark slot", () => {
  it("leaves the slot empty when no condition claims it", () => {
    const { container } = render(<DayMarkSlot marks={[]} />);

    expect(container.firstChild).toBeNull();
  });

  it("draws the stale-source mark in amber", () => {
    const { container } = render(<DayMarkSlot marks={[mark("amber")]} />);

    expect(container.firstElementChild).toHaveClass("glyph--notice-attention");
    expect(container.firstElementChild).toHaveClass("week-day__mark--amber");
    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });

  it("draws an informational mark when it is the only condition", () => {
    const { container } = render(<DayMarkSlot marks={[mark("info")]} />);

    expect(container.firstElementChild).toHaveClass("glyph--notice-info");
    expect(container.firstElementChild).toHaveClass("week-day__mark--info");
  });

  it("gives amber the slot over informational while both conditions hold", () => {
    expect(dayHeaderMarkOf([mark("info"), mark("amber")])?.pigment).toBe("amber");
  });
});
