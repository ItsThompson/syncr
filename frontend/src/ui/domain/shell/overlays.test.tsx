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
import { afterEach, describe, expect, it, vi } from "vitest";

import { CommandPalette } from "./CommandPalette";
import { HelpOverlay } from "./HelpOverlay";
import { HELP_KEY, KEYBOARD_MAP, scopeReading } from "./keyboardMap";
import { SCREENS } from "./navigation";

const ACTIONS = [
  { id: "/week", label: "Go to week", group: "Navigate", hint: "g w" },
  { id: "/today", label: "Go to today", group: "Navigate", hint: "g t" },
];

interface RenderedRow {
  readonly keys: string | null;
  readonly action: string | null;
  readonly scope: string | null;
}

/* Whole rows, cell by cell, so a row asserted for its key alone cannot hide a wrong action or a wrong screen, and
 * so a row the map never held is a difference rather than a silent extra. */
function renderedRows(baseElement: Element): RenderedRow[] {
  return [...baseElement.querySelectorAll(".help__row")].map((row) => ({
    keys: cellText(row, ".help__keys"),
    action: cellText(row, ".help__action"),
    scope: cellText(row, ".help__scope"),
  }));
}

function cellText(row: Element, selector: string): string | null {
  return row.querySelector(selector)?.textContent ?? null;
}

/* WHAT REACT SAYS ON THE CONSOLE, WHICH FOR A DUPLICATE KEY IS THE ONLY CHANNEL THAT OBSERVES IT AT ALL.
 *
 * Both streams, as `ui/primitives/__tests__/mounting.test.tsx` takes them: which of the two React writes a
 * message to is React's to change, and a spy on one of them would pass while the defect stood. Restored by the
 * suite's own `afterEach`. */
function captureComplaints(): string[] {
  const complaints: string[] = [];
  const record = (...args: unknown[]): void => {
    complaints.push(args.join(" "));
  };
  vi.spyOn(console, "error").mockImplementation(record);
  vi.spyOn(console, "warn").mockImplementation(record);
  return complaints;
}

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
  afterEach(() => {
    vi.restoreAllMocks();
  });

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
  it("renders every row of the shell's own keyboard map, whole, and nothing besides", async () => {
    const { baseElement } = render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    expect(renderedRows(baseElement)).toEqual(
      KEYBOARD_MAP.map((entry) => ({
        keys: entry.keys,
        action: entry.action,
        scope: scopeReading(entry.scope),
      })),
    );
  });

  /* THE SCREEN A ROW ANSWERS ON, ASSERTED AT BOTH EDGES and against text this file spells out rather than reads
   * back from the map: a row that answers everywhere and a row that answers on one screen. */
  it("says which screen a row answers on", async () => {
    const { baseElement } = render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    const rows = renderedRows(baseElement);
    expect(rows).toContainEqual({ keys: "n", action: "Capture a task", scope: "everywhere" });
    expect(rows).toContainEqual({
      keys: "Escape",
      action: "Clear the selection and close the panel",
      scope: "week",
    });
  });

  /* TWO ROWS MAY CARRY ONE KEY STRING, because one keystroke answers differently depending on the screen. React
   * identifies a sibling by its key, so a key that is the keystroke alone makes the two rows one. Both halves are
   * asserted, and the complaint is the half that bites: measured, React renders both rows anyway, so the row set
   * alone cannot fail. The describe below keeps the complaint honest. */
  it("renders both rows that share a key string, with no complaint from React", async () => {
    const complaints = captureComplaints();
    const { baseElement } = render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    expect(renderedRows(baseElement).filter((row) => row.keys === "Escape")).toEqual([
      { keys: "Escape", action: "Close an overlay", scope: "everywhere" },
      { keys: "Escape", action: "Clear the selection and close the panel", scope: "week" },
    ]);
    expect(complaints).toEqual([]);
  });

  it("says what it lists, which is what each key does and where", async () => {
    render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);

    expect(
      screen.getByRole("dialog", {
        description: "What each key does, and the screen it answers on.",
      }),
    ).toBeInTheDocument();
  });

  /* The global `Escape` row claims an overlay closes on it, and no `useKeyBinding` registers that key outside the
   * week screen: Radix's own dismiss is what answers it. So the row's claim is asserted here rather than assumed. */
  it("closes on Escape, which is what its own global row promises", async () => {
    render(<HelpOverlay />);
    await userEvent.keyboard(HELP_KEY);
    expect(screen.getByRole("dialog", { name: /Keyboard/ })).toBeInTheDocument();

    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).toBeNull();
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

/* THE CANARY FOR THE ONE GUARD THAT RESTS ON A FRAMEWORK'S CONSOLE.
 *
 * A duplicate key changes nothing a test can read: the rows render, in order, and a key is reflected in neither
 * the DOM nor the accessibility tree. React's development warning is the only channel that observes it, and
 * `react` is declared as a caret range, so a minor release that drops or moves that warning would leave the case
 * above green with the defect standing and no signal anywhere.
 *
 * This mounts the defect on its own, over two children this file owns, and asserts the warning arrives. If React
 * stops warning, this reddens and names the reason instead of the guard quietly becoming a tautology. */
describe("the console channel the shared-key case rests on", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("still carries React's complaint about two children under one key", () => {
    const complaints = captureComplaints();

    render(
      <dl>
        {["first", "second"].map((action) => (
          <div key="one key for two">{action}</div>
        ))}
      </dl>,
    );

    expect(complaints.join(" ")).toContain("same key");
  });
});
