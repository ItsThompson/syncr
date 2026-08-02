import { RouteBand } from "./RouteBand";

export function LearnedRoute() {
  return (
    <RouteBand title="Learned" sub="values, sample counts, confidence">
      <p className="text-base text-ink-soft">
        Per-parameter rows with a bounded maturity meter. Collecting a baseline is a normal state
        and is never marked as a warning.
      </p>
    </RouteBand>
  );
}
