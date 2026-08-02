import { RouteBand } from "./RouteBand";

/* The no-match surface, inside the gate.
 *
 * Without it an unmatched path renders React Router's own developer error page: "Unexpected
 * Application Error!", a "Hey developer" line with two emoji, a system sans-serif, an italic, and an
 * inline `rgba(200,200,200,0.5)` with a hard-coded `padding: 2px 4px`. Off-brand on six counts at
 * once, reachable from the URL bar by a typo, and addressed to the wrong audience.
 *
 * This is a holding surface, not the error screen. The real one, with its plate and its named
 * degradations, belongs to the ticket that owns error states; this keeps a typo inside the design
 * language until then, and it is one route entry rather than a body a later ticket has to graft on. */
export function NotFoundRoute() {
  return (
    <RouteBand title="Not found" sub="no screen answers this address">
      <p className="text-base text-ink-soft">
        Check the address, or use the navigation. Nothing was changed.
      </p>
    </RouteBand>
  );
}
