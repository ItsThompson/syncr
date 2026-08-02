import { RouteBand } from "./RouteBand";

export function TemplatesRoute() {
  return (
    <RouteBand title="Templates" sub="day shapes, week pattern, habits, anchor types">
      <p className="text-base text-ink-soft">
        Each tab is a list plus an editor. The rotation cursor is shown read-only with its
        provenance, because editing derived state desyncs it from the log that produced it.
      </p>
    </RouteBand>
  );
}
