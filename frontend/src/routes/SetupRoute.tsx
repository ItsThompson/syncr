import { RouteBand } from "./RouteBand";

export function SetupRoute() {
  return (
    <RouteBand title="Setup" sub="first run">
      <p className="text-base text-ink-soft">
        Four things have to exist before syncr can solve. This route walks them, and it is
        resumable: configuration across several sittings must not be trapped in a modal.
      </p>
    </RouteBand>
  );
}
