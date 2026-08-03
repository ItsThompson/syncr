/* One global keystroke, bound where the map says it belongs.
 *
 * THE PLATFORM MODIFIER IS RESOLVED HERE AND NOWHERE ELSE. `Cmd+K` on a Mac and `Ctrl+K` everywhere else are one
 * binding, and a component that asked `event.metaKey` itself would answer wrongly on one platform and would put
 * the same conditional in every consumer.
 *
 * A CHORD WITH A MODIFIER FIRES WHILE THE READER IS TYPING; a bare key does not. The palette has to be reachable
 * from inside the field a reader is typing into, which is the whole reason capture and search are global, and a
 * bare `?` in a title has to stay a question mark.
 *
 * The handler is held in a ref so the listener is attached once per binding rather than once per render: a fresh
 * closure on every render would detach and re-attach the document listener under every keystroke the app draws
 * for.
 *
 * A HELD KEY FIRES ONCE. `event.repeat` is true for every repeat the platform sends, and a binding that opened a
 * dialog would otherwise re-run its handler thirty times a second for as long as a reader leans on the key. Both
 * current consumers set state that is already set, so this costs nothing today and is the guard the first binding
 * that does real work would need. */

import { useEffect, useRef } from "react";

import { isTyping } from "./typing";

export interface KeyBinding {
  /** The `event.key` value, as the platform reports it: `?`, `k`, `Escape`. */
  readonly key: string;
  /** True for a chord: Command on an Apple platform, Control everywhere else. */
  readonly withPlatformModifier?: boolean | undefined;
}

/** True on a platform whose primary modifier is Command rather than Control. */
export function isApplePlatform(): boolean {
  const platform = navigator.platform === "" ? navigator.userAgent : navigator.platform;
  return /mac|iphone|ipad|ipod/i.test(platform);
}

/** True when the event carries the platform's own primary modifier. */
export function hasPlatformModifier(event: KeyboardEvent): boolean {
  return isApplePlatform() ? event.metaKey : event.ctrlKey;
}

function matches(key: string, withPlatformModifier: boolean, event: KeyboardEvent): boolean {
  if (event.repeat) return false;
  if (event.key !== key) return false;
  if (withPlatformModifier) return hasPlatformModifier(event);
  if (event.metaKey || event.ctrlKey || event.altKey) return false;
  return !isTyping(event.target);
}

export function useKeyBinding(binding: KeyBinding, onMatch: () => void): void {
  const { key, withPlatformModifier = false } = binding;
  const latest = useRef(onMatch);

  useEffect(() => {
    latest.current = onMatch;
  });
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (!matches(key, withPlatformModifier, event)) return;
      event.preventDefault();
      latest.current();
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [key, withPlatformModifier]);
}
