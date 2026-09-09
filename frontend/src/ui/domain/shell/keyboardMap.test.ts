/* WHAT THE MAP SAYS THE KEYBOARD DOES, CROSSED AGAINST WHAT THE TREE ACTUALLY BINDS.
 *
 * The map's rule is that an entry arrives with its binding. A rule kept in a comment is worth nothing once the
 * tree moves under it, so it is measured here rather than read: every binding the shipped source registers is
 * collected out of that source, and a row nothing answers fails.
 *
 * WHERE a row says it answers is half of the claim, so the file registering the binding has to belong to the
 * row's own scope: the route's own files for a route row, and any file outside `routes/` for a global one.
 * Without that half, the global `Escape` row would be satisfied by the week screen's `Escape`, which is the
 * confusion the scope exists to end.
 *
 * TWO MECHANISMS ANSWER A KEYSTROKE IN A WAY THIS FILE CAN READ, and every other one is declared. `useKeyBinding`
 * is a call, read out of the source by `scripts/lib/key-bindings.ts`, which the week grid's own keyboard claim
 * reads through as well. A `g` chord is resolved by `useScreenChords` against the screen table, so a chord row is
 * answered by a screen's own letter plus a file that mounts the hook over that table. The rest
 * are invisible here -- Radix's own dismiss, an element's own `onKeyDown`, the drag's window listener -- and a row
 * that needs one names the mechanism. A declaration is held at both edges: it must name a row the map holds, and
 * it must be needed, so a declaration for a row the scan can already see fails rather than passing the row twice
 * over.
 *
 * THE OTHER DIRECTION IS NOT THIS FILE'S. A binding with no row is a gap in the overlay rather than a false
 * statement in it, and the map does not yet carry a row for every binding the routes register. */

import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  keyRegistrationsIn,
  shippedSources,
  type KeyRegistration,
} from "../../../../scripts/lib/key-bindings.ts";
import { appSourceDir } from "../../../../scripts/lib/paths.ts";
import {
  CAPTURE_KEY,
  HELP_KEY,
  KEYBOARD_MAP,
  PALETTE_KEY,
  scopeReading,
  type KeyBindingEntry,
  type KeyBindingScope,
} from "./keyboardMap";
import { SCREENS } from "./navigation";

/** A `useKeyBinding` call as the source makes it. `key` is null when its spelling cannot be resolved here. */
type Registration = KeyRegistration;

interface Census {
  readonly registrations: readonly Registration[];
  /** The files that mount the chord hook over the screen table, which is what makes a `g` chord listen. */
  readonly chordHosts: readonly string[];
}

/** A row answered by something no scan can see, and the mechanism that answers it. */
interface Declaration {
  readonly scope: KeyBindingScope;
  readonly keys: string;
  readonly by: string;
}

const DECLARED: readonly Declaration[] = [
  {
    scope: "global",
    keys: "Escape",
    by: "Radix's own dismiss, which every overlay in the kit takes from `Dialog`",
  },
];

/** The exported constants a binding may name in place of spelling its key. */
const NAMED_KEYS = new Map<string, string>([
  ["CAPTURE_KEY", CAPTURE_KEY],
  ["HELP_KEY", HELP_KEY],
  ["PALETTE_KEY", PALETTE_KEY],
]);

/** A row spells a key as a reader says it; this is what each glyph registers as. */
const GLYPH_KEYS = new Map<string, string>([
  ["↑", "ArrowUp"],
  ["↓", "ArrowDown"],
]);

const CHORD_HOST = /useScreenChords\(\s*SCREENS\s*\)/;
const CHORD_ROW = /^g (\S)$/;
const PLATFORM_MODIFIER = "Cmd/Ctrl";
const SHIFT = "Shift";
const ROUTE_AREA = "routes";

/* The census reads the source through `scripts/lib/key-bindings.ts`, which owns the call shape and the two
 * exclusions. The chord hook is read here, because a chord is this shell's own mechanism rather than a binding. */
const census: Promise<Census> = (async () => {
  const sources = await shippedSources();

  return {
    registrations: sources.flatMap((source) => keyRegistrationsIn(source, NAMED_KEYS)),
    chordHosts: sources.filter(({ code }) => CHORD_HOST.test(code)).map(({ file }) => file),
  };
})();

/** What a row's reader-facing spelling asks of a binding. */
interface Advertised {
  readonly key: string;
  readonly withPlatformModifier: boolean;
  readonly withShift: boolean;
}

function advertisedBy(keys: string): Advertised | null {
  const tokens = keys.split("+");
  const spelling = tokens.at(-1) ?? "";
  const modifiers = tokens.slice(0, -1);
  if (spelling === "") return null;
  if (modifiers.some((token) => token !== PLATFORM_MODIFIER && token !== SHIFT)) return null;

  const withPlatformModifier = modifiers.includes(PLATFORM_MODIFIER);
  /* A chord's letter is spelt as a reader says it, upper case, while the platform reports the unshifted value
   * the binding registers. */
  const registered = withPlatformModifier ? spelling.toLowerCase() : spelling;
  return {
    key: GLYPH_KEYS.get(registered) ?? registered,
    withPlatformModifier,
    withShift: modifiers.includes(SHIFT),
  };
}

function answers(registration: Registration, advertised: Advertised): boolean {
  if (registration.key === null) return false;
  if (registration.key !== advertised.key) return false;
  if (registration.withPlatformModifier !== advertised.withPlatformModifier) return false;
  /* A binding that requires Shift and a row that does not say so are two different keystrokes. The reverse is
   * allowed: `event.key` already carries the shifted glyph for most keys, so `Shift+X` is registered either as
   * `X` or as `X` with the flag. */
  return advertised.withShift || !registration.withShift;
}

function relativeToSource(file: string): string {
  return path.relative(appSourceDir, file).split(path.sep).join("/");
}

/** True when a file belongs to the route a scope names, or, for a global row, to no route at all. */
function isOnScope(scope: KeyBindingScope, file: string): boolean {
  const relative = relativeToSource(file);
  if (scope === "global") return !relative.startsWith(`${ROUTE_AREA}/`);
  /* A route's own files carry its segment two ways, the directory `routes/today/` and the component
   * `routes/WeekRoute.tsx`, so the segment is matched without regard to case. */
  return relative.toLowerCase().startsWith(`${ROUTE_AREA}/${scope.slice(1).toLowerCase()}`);
}

type Answer =
  | { readonly kind: "bound"; readonly by: string }
  | { readonly kind: "chord" }
  | { readonly kind: "declared"; readonly by: string }
  | { readonly kind: "unanswered"; readonly why: string };

function chordAnswer(letter: string, entry: KeyBindingEntry, taken: Census): Answer {
  if (entry.scope !== "global") {
    return {
      kind: "unanswered",
      why: `the shell resolves \`${entry.keys}\` on every screen, so it cannot answer on ${entry.scope} alone`,
    };
  }
  if (!SCREENS.some((screen) => screen.chord === letter)) {
    return { kind: "unanswered", why: `no screen answers to \`${entry.keys}\`` };
  }
  if (taken.chordHosts.length === 0) {
    return { kind: "unanswered", why: "nothing mounts the chord hook over the screen table" };
  }
  return { kind: "chord" };
}

function answerFor(
  entry: KeyBindingEntry,
  taken: Census,
  declared: readonly Declaration[],
): Answer {
  const chord = CHORD_ROW.exec(entry.keys);
  if (chord !== null) return chordAnswer(chord[1], entry, taken);

  const advertised = advertisedBy(entry.keys);
  if (advertised === null) {
    return {
      kind: "unanswered",
      why: `\`${entry.keys}\` is spelt in a way this check cannot read`,
    };
  }

  const bound = taken.registrations.filter((candidate) => answers(candidate, advertised));
  const onScope = bound.find((candidate) => isOnScope(entry.scope, candidate.file));
  if (onScope !== undefined) return { kind: "bound", by: relativeToSource(onScope.file) };

  const declaration = declared.find(
    (each) => each.keys === entry.keys && each.scope === entry.scope,
  );
  if (declaration !== undefined) return { kind: "declared", by: declaration.by };

  if (bound.length === 0) return { kind: "unanswered", why: `nothing binds \`${entry.keys}\`` };
  return {
    kind: "unanswered",
    why: `\`${entry.keys}\` is bound in ${bound.map((each) => relativeToSource(each.file)).join(", ")}, and none of those answers on ${entry.scope}`,
  };
}

interface Unanswered {
  readonly row: string;
  readonly why: string;
}

function unansweredIn(taken: Census, declared: readonly Declaration[]): Unanswered[] {
  return KEYBOARD_MAP.flatMap((entry) => {
    const answer = answerFor(entry, taken, declared);
    if (answer.kind !== "unanswered") return [];
    return [{ row: `${entry.scope} ${entry.keys}`, why: answer.why }];
  });
}

describe("the keyboard map", () => {
  it("holds no row for a key nothing binds", async () => {
    expect(unansweredIn(await census, DECLARED)).toEqual([]);
  });

  it("resolves the key of every binding it reads, so a spelling it cannot read is not a pass", async () => {
    const unresolved = (await census).registrations
      .filter((registration) => registration.key === null)
      .map((registration) => `${relativeToSource(registration.file)}: ${registration.options}`);

    expect(unresolved).toEqual([]);
  });

  it("declares a mechanism only for a row the map holds", () => {
    const stale = DECLARED.filter(
      (declaration) =>
        !KEYBOARD_MAP.some(
          (entry) => entry.scope === declaration.scope && entry.keys === declaration.keys,
        ),
    ).map((declaration) => `${declaration.scope} ${declaration.keys}`);

    expect(stale).toEqual([]);
  });

  it("declares a mechanism only where the binding is out of the scan's reach", async () => {
    const outOfReach = new Set(unansweredIn(await census, []).map((each) => each.row));
    const redundant = DECLARED.map(
      (declaration) => `${declaration.scope} ${declaration.keys}`,
    ).filter((row) => !outOfReach.has(row));

    expect(redundant).toEqual([]);
  });

  it("gives one key on one screen a single row", () => {
    const claims = KEYBOARD_MAP.map((entry) => `${entry.scope} ${entry.keys}`);

    expect(claims).toEqual([...new Set(claims)]);
  });

  it("scopes every row either everywhere or to a screen the shell's own table holds", () => {
    const unknown = KEYBOARD_MAP.filter(
      (entry) => entry.scope !== "global" && !SCREENS.some((screen) => screen.path === entry.scope),
    ).map((entry) => `${entry.scope} ${entry.keys}`);

    expect(unknown).toEqual([]);
  });

  it("lists the Today cursor movements on Today, not on the week grid", () => {
    const cursorRows = KEYBOARD_MAP.filter(
      (entry) => entry.scope === "/today" && (entry.keys === "j" || entry.keys === "k"),
    );

    expect(cursorRows).toEqual([
      { keys: "j", action: "Move the cursor to the next row", scope: "/today" },
      { keys: "k", action: "Move the cursor to the previous row", scope: "/today" },
    ]);
  });
});

describe("the screen a row answers on, as the overlay says it", () => {
  const READINGS: [KeyBindingScope, string][] = [
    ["global", "everywhere"],
    ["/week", "week"],
    ["/settings", "settings"],
    /* A route the sidebar does not carry has no name to give, so the path is what a reader gets. */
    ["/setup", "/setup"],
  ];

  it.each(READINGS)("reads %s as %s", (scope, reading) => {
    expect(scopeReading(scope)).toBe(reading);
  });
});

function boundIn(
  file: string,
  key: string,
  modifiers: { readonly withPlatformModifier?: boolean; readonly withShift?: boolean } = {},
): Registration {
  return {
    file,
    key,
    options: `key: "${key}"`,
    withPlatformModifier: modifiers.withPlatformModifier ?? false,
    withShift: modifiers.withShift ?? false,
  };
}

/* THE CHECK'S OWN EDGES, over rows and a census this file makes up, because a check that only ever sees an honest
 * tree is a check nobody has watched fail. */
describe("the check itself", () => {
  const weekFile = path.join(
    appSourceDir,
    "routes",
    "week",
    "hooks",
    "useWeekScreenInteraction.ts",
  );
  const shellFile = path.join(appSourceDir, "ui", "domain", "shell", "CommandPalette.tsx");

  const TAKEN: Census = {
    registrations: [
      boundIn(weekFile, "j"),
      boundIn(weekFile, "A", { withShift: true }),
      boundIn(shellFile, "k", { withPlatformModifier: true }),
    ],
    chordHosts: [path.join(appSourceDir, "ui", "domain", "shell", "ShellLayout.tsx")],
  };

  function answer(entry: KeyBindingEntry, declared: readonly Declaration[] = []): Answer {
    return answerFor(entry, TAKEN, declared);
  }

  it("answers a row whose key its own route binds", () => {
    expect(answer({ keys: "j", action: "Down a block", scope: "/week" })).toEqual({
      kind: "bound",
      by: "routes/week/hooks/useWeekScreenInteraction.ts",
    });
  });

  it("refuses a row for a key nothing binds", () => {
    expect(answer({ keys: "q", action: "Quit", scope: "/week" })).toEqual({
      kind: "unanswered",
      why: "nothing binds `q`",
    });
  });

  it("refuses a row bound only outside the screen it names", () => {
    expect(answer({ keys: "j", action: "Down a block", scope: "/today" })).toEqual({
      kind: "unanswered",
      why: "`j` is bound in routes/week/hooks/useWeekScreenInteraction.ts, and none of those answers on /today",
    });
  });

  it("refuses a global row for a key only a route binds", () => {
    expect(answer({ keys: "j", action: "Down a block", scope: "global" })).toEqual({
      kind: "unanswered",
      why: "`j` is bound in routes/week/hooks/useWeekScreenInteraction.ts, and none of those answers on global",
    });
  });

  it("reads a chord as answered by the screen table and the hook that resolves it", () => {
    expect(answer({ keys: "g w", action: "Go to week", scope: "global" })).toEqual({
      kind: "chord",
    });
  });

  it("refuses a chord no screen answers to", () => {
    expect(answer({ keys: "g q", action: "Go to nowhere", scope: "global" })).toEqual({
      kind: "unanswered",
      why: "no screen answers to `g q`",
    });
  });

  it("refuses a chord scoped to one screen, because the shell resolves it on all of them", () => {
    expect(answer({ keys: "g w", action: "Go to week", scope: "/week" })).toEqual({
      kind: "unanswered",
      why: "the shell resolves `g w` on every screen, so it cannot answer on /week alone",
    });
  });

  it("reads a platform chord against the unshifted key the binding registers", () => {
    expect(answer({ keys: "Cmd/Ctrl+K", action: "Open the palette", scope: "global" })).toEqual({
      kind: "bound",
      by: "ui/domain/shell/CommandPalette.tsx",
    });
  });

  it("refuses a row that hides a modifier the binding requires", () => {
    expect(answer({ keys: "A", action: "Approve", scope: "/week" })).toEqual({
      kind: "unanswered",
      why: "nothing binds `A`",
    });
  });

  it("answers a row that says Shift where the binding requires it", () => {
    expect(answer({ keys: "Shift+A", action: "Approve", scope: "/week" })).toEqual({
      kind: "bound",
      by: "routes/week/hooks/useWeekScreenInteraction.ts",
    });
  });

  it("refuses a spelling it cannot read rather than passing it", () => {
    expect(answer({ keys: "Meta+Space", action: "Something", scope: "global" })).toEqual({
      kind: "unanswered",
      why: "`Meta+Space` is spelt in a way this check cannot read",
    });
  });

  it("answers a row a declaration covers, and names the mechanism", () => {
    const declared: Declaration[] = [
      { scope: "global", keys: "Escape", by: "Radix's own dismiss" },
    ];

    expect(
      answer({ keys: "Escape", action: "Close an overlay", scope: "global" }, declared),
    ).toEqual({
      kind: "declared",
      by: "Radix's own dismiss",
    });
  });
});
