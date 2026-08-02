/* The dialog: the only family carrying --shadow-hard, and the only ink-filled surface in the product.
 *
 * The header is wrapped in `on-ink-surface`, which is the whole point of the component's structure: the focus
 * ring is chosen by the surface it LANDS on, so `base.css` gives any focusable descendant of that class the
 * inverse ring. A control added to the header by a later ticket inherits the right ring without knowing the
 * rule exists. --ink-bright on --ink-deep measures 1.61:1 and vanishes; --paper-raised on it measures 14.83:1,
 * both computed in `Input.contrast.test.ts`. */

import { readFile } from "node:fs/promises";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { srcDir } from "../../testing/compileTheme";
import { kitStylesheet } from "../../testing/kitStylesheets";
import { Button } from "./Button";
import { Dialog } from "./Dialog";

function renderDialog(props: Partial<Parameters<typeof Dialog>[0]> = {}) {
  const onOpenChange = vi.fn<(next: boolean) => void>();
  const result = render(
    <Dialog
      isOpen
      onOpenChange={onOpenChange}
      title="Approve week · Mon 10 to Sun 16"
      footer={<Button>Approve</Button>}
      {...props}
    >
      <p>91 blocks will be written to the calendar.</p>
    </Dialog>,
  );
  return { onOpenChange, ...result };
}

describe("Dialog", () => {
  it("is a modal named by its title", () => {
    renderDialog();

    expect(
      screen.getByRole("dialog", { name: /Approve week · Mon 10 to Sun 16/ }),
    ).toBeInTheDocument();
  });

  it("renders nothing at all while closed, so there is no fade in either direction", () => {
    renderDialog({ isOpen: false });

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("renders the body and the footer the caller gave it", () => {
    renderDialog();

    expect(screen.getByText("91 blocks will be written to the calendar.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("closes on Escape, which Radix owns rather than this component", async () => {
    const { onOpenChange } = renderDialog();

    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("closes from the dismiss control, which is named for a screen reader", async () => {
    const { onOpenChange } = renderDialog();

    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("draws the dismiss mark from the glyph table", () => {
    const { baseElement } = renderDialog();

    expect(baseElement.querySelector(".glyph--dismiss")).not.toBeNull();
  });

  it("traps focus, so a keyboard cannot leave a modal by tabbing", async () => {
    renderDialog();

    await userEvent.tab();
    await userEvent.tab();
    await userEvent.tab();

    expect(screen.getByRole("dialog").contains(document.activeElement)).toBe(true);
  });

  it("carries a description where the body is not prose", () => {
    renderDialog({ description: "Approving writes the week to the calendar." });

    expect(
      screen.getByRole("dialog", { description: "Approving writes the week to the calendar." }),
    ).toBeInTheDocument();
  });
});

/* THE INK SURFACE AND THE RING THAT FOLLOWS FROM IT. */
describe("the dialog's header", () => {
  it("is the one surface wrapped in on-ink-surface", () => {
    const { baseElement } = renderDialog();
    const header = baseElement.querySelector("header");

    expect([...(header?.classList ?? [])]).toContain("on-ink-surface");
    expect(baseElement.querySelectorAll(".on-ink-surface")).toHaveLength(1);
  });

  it("takes the ink fill and the text made for it", async () => {
    const css = await kitStylesheet("Dialog.css");
    const header = /\.dialog__header\s*\{([^}]*)\}/.exec(css);

    expect(header?.[1]).toContain("background: var(--ink-deep)");
    expect(header?.[1]).toContain("color: var(--on-ink)");
  });

  it("inherits the inverse ring from the base layer rather than declaring one", async () => {
    const base = await readFile(path.join(srcDir, "base.css"), "utf8");

    expect(base).toContain(".on-ink-surface :focus-visible");
    expect(base).toContain("var(--state-focus-ring-inverse)");
    expect((await kitStylesheet("Dialog.css")).replace(/\/\*[\s\S]*?\*\//g, "")).not.toContain(
      "outline",
    );
  });

  it("gives a control added to it later the inverse ring, without that control knowing", () => {
    render(
      <Dialog isOpen onOpenChange={() => {}} title="Approve">
        <p>Body</p>
      </Dialog>,
    );
    const header = screen.getByRole("dialog").querySelector("header");
    const dismiss = screen.getByRole("button", { name: "Close" });

    // The rule is a descendant selector on the container, so anything focusable inside it is covered.
    expect(header?.contains(dismiss)).toBe(true);
  });
});

describe("the dialog's lift", () => {
  it("comes from the shared overlay class rather than from this component", () => {
    const { baseElement } = renderDialog();
    const panel = baseElement.querySelector(".dialog");

    expect([...(panel?.classList ?? [])]).toContain("overlay");
  });

  it("is the one hard offset, and the scrim is derived rather than a new pigment", async () => {
    const css = await kitStylesheet("overlay.css");

    expect(css).toContain("box-shadow: var(--shadow-hard)");
    expect(css).toContain("background: var(--scrim)");
  });

  it("centres without a transform, because motion's property list bans one", async () => {
    const css = await kitStylesheet("overlay.css");
    const declarations = css.replace(/\/\*[\s\S]*?\*\//g, "");

    expect(declarations).toContain("place-items: center");
    expect(declarations).not.toContain("translate:");
  });
});
