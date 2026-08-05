/* How a preference reads in one table cell, and what a draft of one sends back.
 *
 * `05:30 or 13:15 · strong` AND `morning · soft` ARE THE SAME FORM, not two. A window is a stretch of the day,
 * and what a reader needs from it is when the work starts: `05:30 or 13:15` is the two starts joined. Where a
 * single window happens to be exactly a named part of the day, the name is shorter and reads better, so the
 * name is used. Both are one function over the same data.
 *
 * THE DAYPARTS ARE AN EXACT MATCH, NOT A CLASSIFICATION. `06:00 to 12:00` reads as `morning`; `06:15 to 12:00`
 * reads as `06:15`. A tolerance would make two different preferences read identically, which is worse than a
 * clock time for the reader who authored one deliberately. The vocabulary is closed at three, and a stretch
 * across midnight is not among them because the api refuses one: a window sits inside a single local day.
 *
 * A DRAFT IS THE WHOLE PREFERENCE. The api replaces wholly rather than merging, so a draft carries every field
 * and a cleared one is null afterwards. There is no merge rule to express and no field-by-field edit to model.
 *
 * A DRAFT'S WINDOW CARRIES A LOCAL ID AND THE WIRE'S DOES NOT. Two windows a reader is midway through editing
 * can hold identical bounds, so nothing in their values identifies a row; an id minted when the row appears is
 * what lets the form keep the caret in the field being typed into. It is stripped on submit, because the api's
 * shape is two clock times and an identifier it never issued would be a field it has to refuse. */

import type {
  AreaPreferenceBody,
  EffectivePreference,
  Preference,
  PreferenceStrength,
  PreferenceWindow,
} from "../../api/hooks/usePreferences";
import { asFieldText, figureOf, figureRefusal, readFigure } from "./figures";

/** U+00B7 MIDDLE DOT, which is how this product joins two readings inside one cell. */
const JOIN = " \u00b7 ";
const NOTHING = "\u2014";

/** What a cell reads when neither the Area nor anything above it declares a preference. */
export const NO_PREFERENCE = NOTHING;

/** One window as the form holds it: the bounds, and an identity the wire does not carry. */
export interface WindowDraft {
  readonly id: string;
  readonly start: string;
  readonly end: string;
}

/** A preference as the form holds it: every field the api replaces, and the windows with their ids.
 *
 * THE CAP IS TEXT LIKE EVERY OTHER FIGURE FIELD ON THIS SCREEN. A number-shaped draft round-trips each keystroke
 * through `text -> number -> text`, which swallows a trailing point as it is typed and clears a mistyped letter
 * rather than showing it: the reader cannot see themselves typing. It is parsed once, on submit.
 */
export interface PreferenceDraft {
  readonly windows: readonly WindowDraft[];
  readonly strength: PreferenceStrength;
  readonly preferredDurationMinutes: number | null;
  readonly maxPerDayMinutes: string;
}

export const DAYPARTS: readonly {
  readonly name: string;
  readonly start: string;
  readonly end: string;
}[] = [
  { name: "morning", start: "06:00", end: "12:00" },
  { name: "afternoon", start: "12:00", end: "18:00" },
  { name: "evening", start: "18:00", end: "23:00" },
];

/** A stored wall time as the cell reads it, which is `HH:MM` with the seconds the wire carries dropped. */
export function asClock(wallTime: string): string {
  return wallTime.slice(0, 5);
}

/** What the windows of a preference are called: a daypart's name, or the starts joined by `or`. */
export function windowPhrase(windows: readonly PreferenceWindow[]): string {
  if (windows.length === 0) return "no preferred time";
  const only = windows.length === 1 ? windows[0] : undefined;
  const named =
    only === undefined
      ? undefined
      : DAYPARTS.find(
          (part) => asClock(only.start) === part.start && asClock(only.end) === part.end,
        );
  if (named !== undefined) return named.name;
  return windows.map((window) => asClock(window.start)).join(" or ");
}

/** The whole cell: `05:30 or 13:15 · strong`, `morning · soft`, or a dash. */
export function preferenceCellText(effective: EffectivePreference | null | undefined): string {
  if (effective === null || effective === undefined) return NO_PREFERENCE;
  return `${windowPhrase(effective.windows)}${JOIN}${effective.strength}`;
}

/** The draft a cell opens with: the Area's own declaration, or an empty one when it has none. */
export function draftOf(preference: Preference | undefined): PreferenceDraft {
  const declared = preference?.declared;
  return {
    windows:
      declared?.windows.map((window, index) => ({
        id: `stored-${index}`,
        start: asClock(window.start),
        end: asClock(window.end),
      })) ?? [],
    strength: declared?.strength ?? "soft",
    preferredDurationMinutes: declared?.preferredDurationMinutes ?? null,
    maxPerDayMinutes: asFieldText(declared?.maxPerDayMinutes ?? null),
  };
}

/** The body a submit sends. The local ids go: the api's window is two clock times and nothing else. */
export function bodyOf(draft: PreferenceDraft): AreaPreferenceBody {
  return {
    windows: draft.windows.map((window) => ({ start: window.start, end: window.end })),
    strength: draft.strength,
    preferredDurationMinutes: draft.preferredDurationMinutes,
    maxPerDayMinutes: figureOf(readFigure(draft.maxPerDayMinutes)),
  };
}

/** Why the cap cannot be sent, in the reader's words, or null when it can. */
export function capRefusal(draft: PreferenceDraft): string | null {
  return figureRefusal(draft.maxPerDayMinutes, "A daily cap");
}

/** A draft with one window's bounds replaced, which is what editing a clock field produces. */
export function withWindow(
  draft: PreferenceDraft,
  id: string,
  bounds: { readonly start: string; readonly end: string },
): PreferenceDraft {
  return {
    ...draft,
    windows: draft.windows.map((window) => (window.id === id ? { id, ...bounds } : window)),
  };
}

/** A draft with one more window, prefilled with the morning, which is the commonest declaration. */
export function withAnotherWindow(draft: PreferenceDraft, id: string): PreferenceDraft {
  const morning = DAYPARTS[0];
  return { ...draft, windows: [...draft.windows, { id, start: morning.start, end: morning.end }] };
}

/** A draft with one window dropped. An empty list is a statement, not an omission. */
export function withoutWindow(draft: PreferenceDraft, id: string): PreferenceDraft {
  return { ...draft, windows: draft.windows.filter((window) => window.id !== id) };
}

/** A draft at another strength. */
export function withStrength(
  draft: PreferenceDraft,
  strength: PreferenceStrength,
): PreferenceDraft {
  return { ...draft, strength };
}

/** A draft with another daily cap, as the reader typed it. A cap is an Area's alone, which is why it lives here. */
export function withCap(draft: PreferenceDraft, text: string): PreferenceDraft {
  return { ...draft, maxPerDayMinutes: text };
}

/** A draft with another ideal session length, or none. */
export function withIdealDuration(draft: PreferenceDraft, minutes: number | null): PreferenceDraft {
  return { ...draft, preferredDurationMinutes: minutes };
}
