/* A horizontal band: the top bar, the summary strip above the week grid, and a readout row.
 *
 * IT HOLDS THE RHYTHM AND NOT THE HEIGHT. A band that reserved a height would be a container carrying one
 * screen's correctness rule: the summary strip's height is fixed so the grid beneath it cannot shift mid-drag,
 * which is a fact about the week screen, and it is reserved by the strip's own layer-2 sheet. `Strip.css` states
 * why the variant that used to live here was the wrong home for it.
 */

import type { ReactNode } from "react";

import "./Strip.css";

export interface StripProps {
  readonly children: ReactNode;
}

export function Strip({ children }: StripProps) {
  return <div className="strip">{children}</div>;
}
