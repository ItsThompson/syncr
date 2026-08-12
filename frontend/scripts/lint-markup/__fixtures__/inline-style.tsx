/* Fixture: the inline `style` prop, which stylelint never sees because it reads stylesheets only.
 *
 * Element 1 sets what the design language forbids absolutely, in CSS spelling.
 * Element 2 sets a computed length, a custom property and a square radius, which is how the week grid
 * has to work and how the sheets pass an Area's ink, so none of the three may be a finding.
 * Elements 3 and 4 are two proved escapes: React writes camelCase, and every rule
 * here was written against the CSS property name with a word boundary in front of it, which does not
 * match inside a camelCase word. Both elements passed all seven checks, and element 3 rendered a real
 * blur on the real sidebar.
 * Element 5 is a circle in a file that is not on the circle allowlist, so the inline form is refused
 * exactly as `rounded-full` would be. */

export function Inline({ topPx, areaToken }: { readonly topPx: number; readonly areaToken: string }) {
  return (
    <div>
      <span style={{ color: "#ff0000", boxShadow: "0 0 8px red", transition: "all 300ms" }} />
      <span style={{ top: `${topPx}px`, "--ai": `var(${areaToken})`, borderRadius: "0" }} />
      <span style={{ backdropFilter: "blur(4px)", willChange: "transform" }} />
      <span style={{ outline: "none", borderRadius: "8px", WebkitFilter: "blur(2px)" }} />
      <span style={{ borderRadius: "50%" }} />
    </div>
  );
}
