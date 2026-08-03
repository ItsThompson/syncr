/* The textarea, which is the one control in the kit that grows.
 *
 * Vertical only: a reader dragging it wider breaks the column the form lives in. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { kitStylesheet } from "../../testing/kitStylesheets";
import { Textarea } from "./Textarea";

describe("Textarea", () => {
  it("hands the caller the value rather than the event", async () => {
    const onValueChange = vi.fn<(next: string) => void>();
    render(<Textarea value="" onValueChange={onValueChange} rows={4} label="Note" />);

    await userEvent.type(screen.getByRole("textbox"), "S");

    expect(onValueChange).toHaveBeenCalledWith("S");
  });

  it("takes its resting height from the caller's rows, so no default nobody chose applies", () => {
    render(<Textarea value="" onValueChange={() => {}} rows={4} label="Note" />);

    expect(screen.getByRole("textbox")).toHaveAttribute("rows", "4");
  });

  it("marks invalid with aria-invalid", () => {
    render(<Textarea value="" onValueChange={() => {}} rows={2} label="Note" isInvalid />);

    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
  });

  it("takes the multiline modifier, which is what widens it to its column and lets it grow", () => {
    render(<Textarea value="" onValueChange={() => {}} rows={2} label="Note" />);

    expect([...screen.getByRole("textbox").classList]).toContain("control--multiline");
  });

  it("resizes vertically only", async () => {
    expect(await kitStylesheet("control.css")).toContain("resize: vertical");
  });
});
