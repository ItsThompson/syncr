/* `/settings`: everything a reader configures once, and the panels that say when something is degraded.
 *
 * EIGHT PANELS, ONE SCREEN, AND THE READS BELONG TO THE ROUTE. Every read on this screen happens here and every
 * component below takes its data as props, so each panel is testable without a network fixture and no component
 * fetches.
 *
 * A PANEL'S READS ARE ITS OWN, which is why the readings are narrowed per section rather than once for the screen.
 * A failure reading the off-plan periods must not blank the sources table: these are six collections behind six
 * requests, and a screen that waited for all of them would be as slow as its slowest read and as broken as its most
 * broken one. `readingOf` makes the same choice one layer down, where a refusal outranks an outstanding read.
 *
 * THE DEGRADATION PANELS SIT AT THE HEAD, WHICH IS WHAT VOLUME 2 MEANS. A reader walks past them to reach the
 * screen's content. Every one of them is composed by the api -- expiry and stopped projection on the connection
 * read, an unreadable feed on the source list itself -- so the banner in the top bar, the panels here and the day
 * notices on Today cannot word one outage differently; only the parse rejection is worded on this screen.
 *
 * NOTHING HERE SPINS AND NOTHING ANIMATES. A sync reports progress by the anchor count in its row changing, and
 * there is no spinner in the kit to reach for even if one were wanted.
 *
 * THE CLOCK AND THE VIEWPORT ARE READ ONCE AND HELD. Staleness is a duration, and a component reading `Date.now()`
 * where it needed one would give two panels two different nows and make a test depend on the wall clock. The
 * viewport height is held for the same reason one layer over: it feeds the zoom cap, and a cap that changed as a
 * window resized would move a select's options under the cursor on a surface where nothing moves. */

import { useState } from "react";

import {
  useCalendarSources,
  useGoogleConnection,
  useGoogleConsent,
  useHorizonEdit,
  useSourceAddition,
  useSourceInclusion,
  useSourceRemoval,
  useSourceSync,
  useWriteTargetRole,
} from "../../api/hooks/useCalendarSources";
import {
  useOffPlanDeclaration,
  useOffPlanEdit,
  useOffPlanPeriods,
  useOffPlanRemoval,
} from "../../api/hooks/useOffPlan";
import { useRoutines } from "../../api/hooks/useRoutines";
import { useReadiness } from "../../api/hooks/useReadiness";
import {
  useSettings,
  useSettingsPatch,
  useTravelOverrideDeclaration,
  useTravelOverrideRemoval,
  useTravelOverrides,
} from "../../api/hooks/useSettings";
import { NoticePanel, noticesAt } from "../../ui/domain";
import { Pane, Panel } from "../../ui/layout";
import { todayIn } from "../../lib/zonedInstant";
import { ApiReading } from "../ApiReading";
import { readingOf } from "../reading";
import { RouteBand } from "../RouteBand";
import { GeometryPanel } from "./components/GeometryPanel";
import { GoogleConsentPanel } from "./components/GoogleConsentPanel";
import { OffPlanPanel } from "./components/OffPlanPanel";
import { ReadingSection } from "./components/ReadingSection";
import { RoutineFloorsPanel } from "./components/RoutineFloorsPanel";
import { SourceAddition } from "./components/SourceAddition";
import { SourcesPanel } from "./components/SourcesPanel";
import { WriteTargetPanel } from "./components/WriteTargetPanel";
import { ZonePanel } from "./components/ZonePanel";
import { statedInstant } from "./format";
import { gridHeightFor } from "./geometry";
import { rejectionPanels } from "./sourceNotices";

/** The zone every instant renders in until the settings read lands. One zone, and never a second one. */
const ZONE_BEFORE_THE_READ = "UTC";

export function SettingsRoute() {
  const [now] = useState(() => Date.now());
  const [viewportHeight] = useState(() => window.innerHeight);

  const settings = useSettings();
  const overrides = useTravelOverrides();
  const sources = useCalendarSources();
  const connection = useGoogleConnection();
  const routines = useRoutines();
  const periods = useOffPlanPeriods();
  const readiness = useReadiness();

  const patch = useSettingsPatch();
  /* A WRITE HOOK PER CONTROL, DELIBERATELY. The hook holds the last refusal, and a refusal belongs to the control
     that caused it: one instance shared across the zone panel and the geometry panel's two fields renders a
     rejected day bound under the home-zone select as well. All three invalidate the same key by name, so the
     reading stays one reading. */
  const hoursPatch = useSettingsPatch();
  const boundsPatch = useSettingsPatch();
  const travelDeclaration = useTravelOverrideDeclaration();
  const travelRemoval = useTravelOverrideRemoval();
  const sourceAddition = useSourceAddition();
  const inclusion = useSourceInclusion();
  const sourceRemoval = useSourceRemoval();
  const sync = useSourceSync();
  const horizon = useHorizonEdit();
  const role = useWriteTargetRole();
  const consent = useGoogleConsent();
  const offPlanDeclaration = useOffPlanDeclaration();
  const offPlanEdit = useOffPlanEdit();
  const offPlanRemoval = useOffPlanRemoval();

  const activeZone = settings.status === "ready" ? settings.data.activeZone : ZONE_BEFORE_THE_READ;
  const today = todayIn(activeZone, now);

  const panels = [
    ...(connection.status === "ready" ? noticesAt("panel", connection.data.notices) : []),
    /* The stale-feed panels are the api's own words, arrived on the source list; the rejection panels are the
       one condition this screen still composes, and both name what survives. */
    ...(sources.status === "ready"
      ? [...noticesAt("panel", sources.data.notices), ...rejectionPanels(sources.data.sources)]
      : []),
  ];

  return (
    <RouteBand title="Settings" sub="sources, write target, zone and travel, geometry, off plan">
      <Pane label="Settings">
        {panels.map((notice) => (
          <NoticePanel
            key={notice.id}
            notice={notice}
            /* `since` reads after the kit's own word, so the instant is what belongs there: `since 4 days` is not
               a sentence, and the duration is already in the detail the api composed. */
            formatSince={(instant) => statedInstant(instant, activeZone)}
          />
        ))}

        <ReadingSection
          reading={readingOf({ listing: sources, connection })}
          title="Reading your calendars"
          detail="Which feeds syncr reads, what each one contributed, and which calendar it writes to."
        >
          {(read) => (
            <>
              <SourcesPanel
                sources={read.listing.sources}
                zone={activeZone}
                inclusion={inclusion}
                removal={sourceRemoval}
                sync={sync}
              />
              <WriteTargetPanel sources={read.listing.sources} horizon={horizon} role={role} />
              <SourceAddition write={sourceAddition} />
              <GoogleConsentPanel connection={read.connection} request={consent} />
            </>
          )}
        </ReadingSection>

        <ReadingSection
          reading={readingOf({ settings, overrides })}
          title="Reading your zone and travel"
          detail="Your home zone, the zone active today, and every range you have declared elsewhere."
        >
          {(read) => (
            <>
              <ZonePanel
                settings={read.settings}
                overrides={read.overrides}
                today={today}
                patch={patch}
                declaration={travelDeclaration}
                removal={travelRemoval}
              />
              <GeometryPanel
                settings={read.settings}
                gridHeightPx={gridHeightFor(viewportHeight)}
                hoursPatch={hoursPatch}
                boundsPatch={boundsPatch}
              />
            </>
          )}
        </ReadingSection>

        <ReadingSection
          reading={readingOf({ routines })}
          title="Reading your routines"
          detail="The circadian frame, and the floor each routine may be compressed to."
        >
          {(read) => <RoutineFloorsPanel routines={read.routines} />}
        </ReadingSection>

        <ReadingSection
          reading={readingOf({ "off-plan periods": periods })}
          title="Reading your off-plan periods"
          detail="Every span you have declared off, and whether the frame survives inside each one."
        >
          {(read) => (
            <OffPlanPanel
              periods={read["off-plan periods"]}
              zone={activeZone}
              today={today}
              declaration={offPlanDeclaration}
              edit={offPlanEdit}
              removal={offPlanRemoval}
            />
          )}
        </ReadingSection>

        {/* The api's own readiness, which is the one reading on this screen about syncr rather than about
            the plan: a database or a migration the api cannot reach is why every panel above would refuse. */}
        <Panel title="Service">
          <ApiReading readiness={readiness} />
        </Panel>
      </Pane>
    </RouteBand>
  );
}
