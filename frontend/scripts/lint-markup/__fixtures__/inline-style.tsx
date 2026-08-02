/* Fixture: the inline `style` prop, which stylelint never sees because it reads stylesheets only.
 *
 * The first element sets what the design language forbids absolutely. The second sets a computed
 * length and a custom property, which is how the week grid has to work and how the sheets pass an
 * Area's ink, so neither may be a finding. */

export function Inline({ topPx, areaToken }: { readonly topPx: number; readonly areaToken: string }) {
  return (
    <div>
      <span style={{ color: "#ff0000", boxShadow: "0 0 8px red", transition: "all 300ms" }} />
      <span style={{ top: `${topPx}px`, "--ai": `var(${areaToken})` }} />
    </div>
  );
}
