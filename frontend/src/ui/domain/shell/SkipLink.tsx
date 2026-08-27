/* The shell's first focusable stop, mounted before the top bar on every screen the shell renders.
 *
 * THE REVEAL LIVES IN `skip-link.css` AS DECLARATIONS UNDER THE STATE SELECTOR, not as a
 * variant-prefixed utility here: `scripts/check-channels` reports a CSS declaration it cannot place
 * but silently skips a markup utility it does not recognize, so only the CSS spelling is enforceable.
 * This file's contract is the bare class name: no variant token may join it.
 */

import "./skip-link.css";

export function SkipLink() {
  return (
    <a className="skip-link" href="#main">
      Skip to content
    </a>
  );
}
