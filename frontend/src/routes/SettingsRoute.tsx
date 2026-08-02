import { useReadiness } from "../api/hooks/useReadiness";
import { ApiReading } from "./ApiReading";
import { RouteBand } from "./RouteBand";

/* The route is where a read happens: it calls the hook and hands the resource down, so every
 * component below it renders from props and is testable without a network fixture. */
export function SettingsRoute() {
  const readiness = useReadiness();

  return (
    <RouteBand title="Settings" sub="sources, write target, zone and travel">
      <p className="text-base text-ink-soft">
        Two of these settings drive the Week screen&rsquo;s geometry, so this screen states the
        effect rather than leaving it to be discovered.
      </p>
      <ApiReading readiness={readiness} />
    </RouteBand>
  );
}
