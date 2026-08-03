/* `g` then a letter, owned by the shell.
 *
 * Owned here rather than per route so a binding cannot be claimed twice: a route that wanted
 * `g t` would have to add a screen to the one table this hook resolves against.
 *
 * A pending `g` is cleared by any key that is not a screen letter, so there is no timer to
 * leak and no window in which a stray keystroke navigates. */

import { useEffect } from "react";
import { useNavigate } from "react-router";

import type { Screen } from "../../ui/domain/shell/navigation";
import { isTyping } from "./typing";

const PREFIX = "g";

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
      const screen = screens.find((candidate) => candidate.chord === event.key);
      if (screen === undefined) return;
      event.preventDefault();
      navigate(screen.path);
    };

    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [navigate, screens]);
}
