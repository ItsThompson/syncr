import { RouteBand } from "./RouteBand";

export function TodayRoute() {
  return (
    <RouteBand title="Today" sub="the ledger">
      <p className="text-base text-ink-soft">
        A checklist in time order rather than a one-column grid, because this screen answers
        whether a block happened.
      </p>
    </RouteBand>
  );
}
