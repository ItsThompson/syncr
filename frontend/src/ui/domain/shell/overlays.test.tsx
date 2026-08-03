/* THE PALETTE AND THE HELP OVERLAY, WHICH ARE THE SHELL'S TWO KEYSTROKES.
 *
 * Both are asserted through the keystroke rather than through a prop, because the binding IS the feature: a palette
 * a reader has to click open is a palette they will not use, and the help overlay exists to answer "what can I
 * press". The map the overlay renders is the shell's own, so the two cannot drift.
 *
 * `Cmd/Ctrl+K` is fired as both modifiers here. The component resolves the platform's own modifier and jsdom's
 * `navigator.platform` is whatever the host reports, so pressing both is what makes the case platform-independent
 * without stubbing a global the component reads once. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CommandPalette } from "./CommandPalette";
import { HelpOverlay } from "./HelpOverlay";
import { HELP_KEY, KEYBOARD_MAP } from "./keyboardMap";
import { SCREENS } from "./navigation";

const ACTIONS = [
  { id: "/week", label: "Go to week", group: "Navigate", hint: "g w" },
  { id: "/today", label: "Go to today", group: "Navigate", hint: "g t" },
];

async function pressPaletteChord(): Promise<void> {
  await userEvent.keyboard("{Meta>}k{/Meta}");
  await userEvent.keyboard("{Control>}k{/Control}");
}

describe("the command palette", () => {
  it("is closed until the platform's shortcut opens it", async () => {
    render(<CommandPalette actions={ACTIONS} onSelect={vi.fn<(id: string) => void>()} />);
    expect(screen.queryByRole("combobox")).toBeNull();

    await pressPaletteChord();

    expect(screen.getByRole("combobox", { name: "Command palette" })).toBeInTheDocument();
  });

  it("puts the caret in the query field, so a reader can type straight away", async () => {
    render(<CommandPalette actions={ACTIONS} onSelect={vi.fn<(id: string) => void>()} />);

    await pressPaletteChord();

    expect(document.activeElement).toBe(screen.getByRole("combobox"));
  });

  it("opens from inside a field, which is the case a modifier chord exists for", async () => {
    render(
      <>
        <input aria-label="Title" />
        <CommandPalette actions={ACTIONS} onSelect={vi.fn<(id: string) => void>()} />
      </>,
    );
    screen.getByLabelText("Title").focus();

    await pressPaletteChord();

    expect(screen.getByRole("combobox", { name: "Command palette" })).toBeInTheDocument();
  });

  it("reports the chosen action and closes itself", async () => {
    const onSelect = vi.fn<(id: string) => void>();
    render(<CommandPalette actions={ACTIONS} onSelect={onSelect} />);
    await pressPaletteChord();

    await userEvent.click(screen.getByText("Go to today"));

    expect(onSelect).toHaveBeenCalledWith("/today");
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("floats on the kit's one hard offset rather than drawing a second shadow", async () => {
    const { baseElement } = render(
      <CommandPalette actions={ACTIONS} onSelect={vi.fn<(id: string) => void>()} />,
    );
    await pressPaletteChord();

    expect(baseElement.querySelector(".overlay.palette")).not.toBeNull();
    expect(baseElement.querySelector(".overlay__scrim")).not.toBeNull();
  });

  it("closes on Escape, which Radix owns rather than this component", async () => {
    render(<CommandPalette actions={ACTIONS} onSelect={vi.fn<(id: string) => void>()} />);
    await pressPaletteChord();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("combobox")).toBeNull();
  });
});

describe("the help overlay", () => {
  it("opens on ?", async () => {
    render(<HelpOverlay />);
    expect(screen.queryByRole("dialog")).toBeNull();

    await userEvent.keyboard(HELP_KEY);

    expect(screen.getByRole("dialog", { name: /Keyboard/ })).toBeInTheDocument();
  });

  it("leaves a question mark a reader is typing alone", async () => {
    render(
      <>
        <input aria-label="Title" />
        <HelpOverlay />
      </>,
    );
    screen.getByLabelText("Title").focus();

    await userEvent.keyboard(HELP_KEY);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  /* IT RENDERS THE SHELL'S MAP RATHER THAN A SECOND COPY. A list of keys the overlay owned itself is the most
   * reliable documentation drift there is, so this asserts the rendered rows ARE the map's. */
  it("renders every row of the shell's own keyboard map", async () => {
    render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    for (const entry of KEYBOARD_MAP) {
      expect(screen.getByText(entry.keys)).toBeInTheDocument();
      expect(screen.getByText(entry.action)).toBeInTheDocument();
    }
  });

  it("renders each key in the one form a key takes: bracketed bare mono text", async () => {
    const { baseElement } = render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    const hints = baseElement.querySelectorAll(".key-hint");
    expect(hints).toHaveLength(KEYBOARD_MAP.length);
    for (const hint of hints) expect(hint.tagName).toBe("KBD");
  });

  it("advertises a navigation chord for every screen, derived from the screen table", async () => {
    render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    for (const screenEntry of SCREENS) {
      expect(screen.getByText(`g ${screenEntry.chord}`)).toBeInTheDocument();
    }
  });
});
