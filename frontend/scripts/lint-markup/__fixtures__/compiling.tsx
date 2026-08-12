/* Fixture: every shape that compiled with Tailwind's own compiler while all six checks
 * stayed green. Four reach real CSS the design language forbids absolutely: a named colour, a raw
 * hex, a blurred shadow, and three negative transform utilities against "motion is zero, without
 * exception". None of them can be fenced by the theme, because none is namespace-driven. */

export function Compiling() {
  return (
    <div className="[color:red] [background:#ff0000] [box-shadow:0_0_8px_red] [--my-var:3px]">
      <span className="-translate-x-2 -rotate-3 -skew-y-2" />
      <span className="md:[color:red]" />
    </div>
  );
}
