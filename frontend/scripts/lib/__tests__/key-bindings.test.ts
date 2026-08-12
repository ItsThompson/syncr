/* The one reader of a `useKeyBinding` call, which two checks cross their own claims against. */

import { describe, expect, it } from "vitest";

import { blankJsComments } from "../comments.ts";
import { keyRegistrationsIn } from "../key-bindings.ts";

const FILE = "src/routes/week/hooks/useWeekScreenInteraction.ts";

/** What a caller reads out of the source, with comments blanked exactly as `shippedSources` blanks them. */
function registrationsIn(code: string, namedKeys?: ReadonlyMap<string, string>) {
  return keyRegistrationsIn({ file: FILE, code: blankJsComments(code) }, namedKeys);
}

describe("keyRegistrationsIn", () => {
  it("reads a spelt key and the modifiers the call requires", () => {
    const registrations = registrationsIn(
      'useKeyBinding({ key: "ArrowUp", withShift: true }, () => {});',
    );

    expect(registrations).toEqual([
      {
        file: FILE,
        key: "ArrowUp",
        options: 'key: "ArrowUp", withShift: true',
        withPlatformModifier: false,
        withShift: true,
      },
    ]);
  });

  it("reads a call that requires no modifier as requiring neither", () => {
    const [registration] = registrationsIn('useKeyBinding({ key: "p" }, () => {});');

    expect(registration.withShift).toBe(false);
    expect(registration.withPlatformModifier).toBe(false);
  });

  it("reads the platform modifier where a call requires it", () => {
    const [registration] = registrationsIn(
      'useKeyBinding({ key: "k", withPlatformModifier: true }, () => {});',
    );

    expect(registration.withPlatformModifier).toBe(true);
  });

  it("resolves a key that names a constant the caller supplies", () => {
    const [registration] = registrationsIn(
      "useKeyBinding({ key: CAPTURE_KEY }, () => {});",
      new Map([["CAPTURE_KEY", "n"]]),
    );

    expect(registration.key).toBe("n");
  });

  /* THE ONE ANSWER THAT COULD HIDE A BINDING IS A GUESS, so an unresolved spelling is null and the caller decides.
   * Both of today's callers refuse it, one by name and one by making its own negative claim fail closed. */
  it("reports a key it cannot resolve as null rather than guessing at it", () => {
    const [registration] = registrationsIn("useKeyBinding({ key: NUDGE_LEFT_KEY }, () => {});");

    expect(registration.key).toBeNull();
    expect(registration.options).toBe("key: NUDGE_LEFT_KEY");
  });

  it("reads every call in a file rather than the first", () => {
    const registrations = registrationsIn(
      'useKeyBinding({ key: "j" }, () => {});\nuseKeyBinding({ key: "k" }, () => {});',
    );

    expect(registrations.map((registration) => registration.key)).toEqual(["j", "k"]);
  });

  it("reads no binding out of a call named in prose, because the comment is blanked", () => {
    expect(registrationsIn('// useKeyBinding({ key: "q" }, () => {});')).toEqual([]);
  });
});
