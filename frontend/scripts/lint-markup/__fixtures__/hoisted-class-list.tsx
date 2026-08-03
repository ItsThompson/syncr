/* The class-list shapes a rule can read, and the two it cannot.
 *
 * `className="tabs rounded-full transition-all"` at the attribute is three findings. The identical string in a
 * module constant was none at all, and the utility count went DOWN when it moved, so the only available signal
 * pointed the wrong way. Each element below is either a shape the scan reads or a shape it must refuse. */

import { cva } from "class-variance-authority";

const HOISTED = "tabs rounded-full transition-all";
const EXTRA = "rounded-full";

const strip = cva("strip", {
  variants: { rank: { lead: "strip--lead", quiet: "strip--quiet" } },
});

export function HoistedClassList({ rank, isWide }: { rank: "lead" | "quiet"; isWide: boolean }) {
  return (
    <div className="panel">
      <span className={HOISTED} />
      <span className={`panel ${EXTRA}`} />
      <span className={strip({ rank })} />
      <span className={isWide ? "panel panel--wide" : "panel"} />
    </div>
  );
}
