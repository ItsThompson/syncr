/* Fixture: a variant map, so a rule cannot be dodged by moving a utility off the element.
 *
 * `cva` is not imported: the scan reads text, the fixture is excluded from the tsconfig and from
 * oxlint, and importing a package this workspace does not declare would be a dangling reference. */

export const button = cva("h-control px-3.25", {
  variants: {
    rank: {
      primary: "bg-ink text-on-ink transition-all",
      ghost: "bg-paper text-ink rounded-lg",
    },
  },
});
