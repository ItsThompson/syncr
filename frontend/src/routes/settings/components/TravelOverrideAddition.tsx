/* Declaring a range in another zone.
 *
 * TWO DATES AND A ZONE, BOTH DATES INCLUSIVE, which is the api's own shape. An overlap with an existing range is a
 * 409 naming both ranges and a reversed pair is a 422 naming the end date, and both are rendered as the api states
 * them: a client-side pre-check would be a second copy of a rule the api already owns, and the copy would be the
 * one that went stale.
 *
 * TWO RANGES THAT ABUT ARE ACCEPTED. Adjacency is not overlap, and a traveller flying home on the day the next
 * trip starts is a real pair of ranges. Nothing here treats it as a mistake. */

import { useState } from "react";

import { FormRow } from "../../../ui/layout";
import { Button, DatePicker, Select } from "../../../ui/primitives";
import { zoneOptions } from "../zones";
import { Refusal } from "./Refusal";
import type { TravelOverrideBody } from "../../../api/hooks/useSettings";
import type { Write } from "../../../api/hooks/useWrite";

export interface TravelOverrideAdditionProps {
  readonly write: Write<TravelOverrideBody>;
  /** Today in the active zone, which is what the date fields open on. */
  readonly today: string;
  /** The home zone, which the zone field starts from because most trips are declared against it. */
  readonly homeZone: string;
}

export function TravelOverrideAddition({ write, today, homeZone }: TravelOverrideAdditionProps) {
  const [startDate, setStartDate] = useState(today);
  const [endDate, setEndDate] = useState(today);
  const [zone, setZone] = useState(homeZone);

  const declare = async () => {
    const applied = await write.submit({ startDate, endDate, zone });
    if (!applied) return;
    setStartDate(today);
    setEndDate(today);
  };

  return (
    <div className="flex flex-col gap-2">
      <FormRow label="From" hint="The first date in the other zone. Inclusive.">
        {(field) => (
          <DatePicker
            id={field.id}
            describedBy={field.describedBy}
            label="From"
            today={today}
            value={startDate}
            onValueChange={setStartDate}
          />
        )}
      </FormRow>
      <FormRow label="To" hint="The last date in the other zone. Inclusive.">
        {(field) => (
          <DatePicker
            id={field.id}
            describedBy={field.describedBy}
            label="To"
            today={today}
            value={endDate}
            onValueChange={setEndDate}
          />
        )}
      </FormRow>
      <FormRow label="Zone" hint="Takes precedence over your home zone inside the range.">
        {(field) => (
          <Select
            id={field.id}
            describedBy={field.describedBy}
            value={zone}
            onValueChange={setZone}
            options={zoneOptions(zone)}
          />
        )}
      </FormRow>
      <div>
        <Button onClick={() => void declare()}>Declare travel</Button>
      </div>
      <Refusal problem={write.problem} />
    </div>
  );
}
