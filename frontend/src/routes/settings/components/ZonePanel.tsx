/* The home zone, the zone active today, and the travel overrides that bend one into the other.
 *
 * THE ACTIVE ZONE IS STATED, WHICH IS THE WHOLE POINT OF THE PANEL. US-SET-04 asks for it and US-TZ-02 asks for
 * it again: a reader has to be able to answer "which zone is syncr using right now" without deducing it from a
 * list of date ranges. The api resolves it through the same function the solver and the assembler read, so the
 * screen and the plan cannot disagree, and the date it was resolved FOR is stated beside it because a zone is
 * only active on a date.
 *
 * ONE ZONE AT A TIME. No time on this screen is shown in two zones, and this panel does not render the home zone's
 * clock beside the active one: two clocks is the thing US-TZ-02 forbids, and a reader comparing them is a reader
 * doing arithmetic the product exists to remove.
 *
 * CHANGING THE HOME ZONE RE-DERIVES THE FRAME. The api bumps the input version of every week from the active date
 * forward, which is what makes the unpinned remainder reflow; this panel states that rather than leaving it to be
 * discovered after a solve moves. */

import { Table, type TableColumn } from "../../../ui/domain";
import { FormRow, Panel } from "../../../ui/layout";
import { Button, Select } from "../../../ui/primitives";
import { zoneOptions } from "../zones";
import { DefinitionRow } from "./DefinitionRow";
import { Refusal } from "./Refusal";
import { TravelOverrideAddition } from "./TravelOverrideAddition";
import type {
  Settings,
  SettingsPatchBody,
  TravelOverride,
  TravelOverrideBody,
  TravelOverrideRemoval,
} from "../../../api/hooks/useSettings";
import type { Write } from "../../../api/hooks/useWrite";

export interface ZonePanelProps {
  readonly settings: Settings;
  readonly overrides: readonly TravelOverride[];
  /** Today in the active zone, which is what a date field opens on. */
  readonly today: string;
  readonly patch: Write<SettingsPatchBody>;
  readonly declaration: Write<TravelOverrideBody>;
  readonly removal: Write<TravelOverrideRemoval>;
}

export function ZonePanel({
  settings,
  overrides,
  today,
  patch,
  declaration,
  removal,
}: ZonePanelProps) {
  const columns: readonly TableColumn<TravelOverride>[] = [
    { key: "from", header: "From", cell: (override) => override.startDate },
    { key: "to", header: "To", cell: (override) => override.endDate },
    { key: "zone", header: "Zone", cell: (override) => override.zone },
    {
      key: "acts",
      header: "",
      cell: (override) => (
        <Button
          rank="quiet"
          size="sm"
          onClick={() => void removal.submit({ overrideId: override.id })}
        >
          Remove
        </Button>
      ),
    },
  ];

  const isTravelling = settings.activeZone !== settings.homeZone;

  return (
    <Panel title="Zone and travel" headerEnd={<span>{settings.activeZone}</span>}>
      <dl className="flex flex-col">
        <DefinitionRow label="active zone">
          {`${settings.activeZone} \u00b7 on ${settings.activeZoneDate}`}
        </DefinitionRow>
        <DefinitionRow label="home zone">{settings.homeZone}</DefinitionRow>
      </dl>
      <p className="text-base text-ink-soft">
        {isTravelling
          ? "A travel override covers today, so the active zone is the override's rather than your home " +
            "zone. Every time in the product renders in it, one zone at a time."
          : "No travel override covers today, so the active zone is your home zone. Every time in the " +
            "product renders in it, one zone at a time."}
      </p>
      <FormRow
        label="Home zone"
        hint={
          "Set once. Changing it re-derives the circadian frame and reflows the unpinned remainder of every " +
          "week from today forward."
        }
      >
        {(field) => (
          <span className="flex flex-wrap items-center gap-3.25">
            <Select
              id={field.id}
              describedBy={field.describedBy}
              value={settings.homeZone}
              onValueChange={(next) => void patch.submit({ homeZone: next })}
              options={zoneOptions(settings.homeZone)}
            />
          </span>
        )}
      </FormRow>
      <Refusal problem={patch.problem} />
      <Table
        columns={columns}
        rows={overrides}
        rowKey={(override) => override.id}
        caption="Travel overrides, with their date ranges and zones"
        countLabel={(count) =>
          count === 0
            ? "No travel declared. Your home zone is in force on every date."
            : `${count} travel override${count === 1 ? "" : "s"}`
        }
      />
      <Refusal problem={removal.problem} />
      <TravelOverrideAddition write={declaration} today={today} homeZone={settings.homeZone} />
    </Panel>
  );
}
