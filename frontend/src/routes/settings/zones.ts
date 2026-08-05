/* The zone identifiers this screen offers, from the runtime's own database.
 *
 * `Intl.supportedValuesOf` RATHER THAN A COMMITTED LIST. A shipped list of IANA identifiers is a copy of tzdata
 * that goes stale the first time a country renames a zone, and the runtime already carries the database the
 * offsets are read from: offering a name the same runtime cannot resolve would be the one inconsistency worth
 * avoiding here.
 *
 * A STORED ZONE THE LIST DOES NOT CARRY IS STILL OFFERED, first. `Intl.supportedValuesOf` enumerates the canonical
 * zones only, so `UTC` and every link name such as `Asia/Calcutta` are absent from it while the same runtime
 * resolves them perfectly well. `UTC` is also the api's own default home zone, so a select that dropped an
 * unenumerated value would render a brand-new tenant's zone as though a different one were set. Whether the runtime
 * can RESOLVE the zone is the question, and it is asked separately from whether the list names it: only a zone that
 * cannot be resolved is marked.
 *
 * NO SEARCH FIELD, because the kit has no combobox and adding one is not this screen's decision. Four hundred
 * options in a select is a long list, and the list is ordered as the database orders it, which is by region. */

import { isKnownZone } from "../../lib/zonedInstant";

/** One zone identifier, as a select offers it. */
export interface ZoneOption {
  readonly value: string;
  readonly label: string;
}

let known: readonly string[] | null = null;

/** Every zone the runtime knows, in the order it lists them. Read once: the list does not change. */
function supportedZones(): readonly string[] {
  if (known !== null) return known;
  known = Intl.supportedValuesOf("timeZone");
  return known;
}

/**
 * The options a zone select offers, with `current` first when the enumerated list does not carry it.
 *
 * `current` may be empty, which is what a form starts from before a zone has been chosen, and an empty value is
 * not an option: a select offering one would let a reader choose nothing and call it a zone.
 */
export function zoneOptions(current: string): readonly ZoneOption[] {
  const supported = supportedZones();
  const listed = supported.map((zone) => ({ value: zone, label: zone }));
  if (current === "" || supported.includes(current)) return listed;
  const label = isKnownZone(current)
    ? current
    : `${current} \u00b7 not in this browser's zone database`;
  return [{ value: current, label }, ...listed];
}
