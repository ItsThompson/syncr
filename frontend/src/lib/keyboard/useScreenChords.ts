/* `g` then a letter, owned by the shell.
 *
 * Owned here rather than per route so a binding cannot be claimed twice: a route that wanted
 * `g t` would have to add a screen to the one table this hook resolves against.
 *
 * A pending `g` is cleared by any key that is not a screen letter, so there is no timer to
 * leak and no window in which a stray keystroke navigates.
 *
 * A CHORD IS ONE GESTURE, so the keystroke that resolves it reaches no other binding, whether or not it names a
 * screen. Without that, two independent listeners answer one keystroke: `g c` navigated nowhere AND confirmed the
 * day, `g m` navigated AND opened a row's moved control, and `g ?` opened the help overlay. The rule lives here
 * rather than in each binding, because the alternative is the same conditional in every consumer.
 *
 * THE LISTENER IS IN THE CAPTURE PHASE, and it has to be. React runs a child's effects before its parent's, so a
 * route's own `useKeyBinding` registers its document listener BEFORE the shell registers this one: in the bubble
 * phase this hook would run second and `stopImmediatePropagation` would arrive after the binding it means to
 * suppress had already fired. Capture runs before every bubble-phase listener on any target, which is the one
 * ordering that does not depend on which component mounted first. */

import { useEffect } from "react";
import { useNavigate } from "react-router";

import type { Screen } from "../../ui/domain/shell/navigation";
import { isTyping } from "./typing";

const PREFIX = "g";

/* Capture, so this hook answers a keystroke before any bare binding does. See the header. */
const CAPTURE = { capture: true } as const;

export function useScreenChords(screens: readonly Screen[]): void {
  const navigate = useNavigate();

  useEffect(() => {
    let isPending = false;

    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      if (isTyping(event.target)) return;

      if (!isPending) {
        isPending = event.key === PREFIX;
        return;
      }

      isPending = false;
      /* Consumed either way. A letter that names no screen still resolved a chord the reader was in the middle
       * of, and a route's bare `p`, `c` or `x` reading it as its own would write on a keystroke the reader spent
       * on navigating. A stray pin is a hard constraint the solver then honours. */
      event.preventDefault();
      event.stopImmediatePropagation();
      const screen = screens.find((candidate) => candidate.chord === event.key);
      if (screen === undefined) return;
      navigate(screen.path);
    };

    document.addEventListener("keydown", onKeyDown, CAPTURE);
    return () => document.removeEventListener("keydown", onKeyDown, CAPTURE);
  }, [navigate, screens]);
}
