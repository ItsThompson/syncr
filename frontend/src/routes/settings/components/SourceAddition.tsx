/* Adding an anchor source, which for an ICS feed is a URL and nothing else.
 *
 * NO OAUTH FOR AN ICS SOURCE, which is why this form takes two fields and no account linking. A
 * university timetable becomes anchors by pasting its address, and the api normalizes the address on the way in,
 * so this form does not try to guess whether `webcal://` should have been `https://`.
 *
 * GOOGLE IS A DIFFERENT ACT AND IT IS NOT THIS FORM. Connecting an account is a consent surface of its own, which
 * names the scopes and the calendars it will read, and `GoogleConsentPanel` owns it. A calendar inside a connected
 * account is then added here by its own identifier, which is why `google` is a provider this form offers: adding a
 * source and granting access are two acts, not one control that behaves differently by provider.
 *
 * THE REFUSAL IS THE API'S OWN SENTENCE. A feed address the api refuses, an internal address it will not fetch,
 * and a duplicate are all stated by the response naming the member, and paraphrasing them here would replace the
 * one sentence written to be read. */

import { useState } from "react";

import { FormRow, Panel } from "../../../ui/layout";
import { Button, Input, Select } from "../../../ui/primitives";
import type { CalendarSourceBody } from "../../../api/hooks/useCalendarSources";
import type { Write } from "../../../api/hooks/useWrite";

const PROVIDERS = [
  { value: "ics", label: "ICS feed" },
  { value: "google", label: "Google calendar" },
] as const;

const HINT_BY_PROVIDER: Readonly<Record<string, string>> = {
  ics: "An ics, webcal, http or https address. No account linking, and no OAuth.",
  google: "The calendar's own identifier, taken as Google states it.",
};

export interface SourceAdditionProps {
  readonly write: Write<CalendarSourceBody>;
}

export function SourceAddition({ write }: SourceAdditionProps) {
  const [provider, setProvider] = useState<CalendarSourceBody["provider"]>("ics");
  const [displayName, setDisplayName] = useState("");
  const [externalId, setExternalId] = useState("");

  const add = async () => {
    const applied = await write.submit({ provider, displayName, externalId });
    if (!applied) return;
    setDisplayName("");
    setExternalId("");
  };

  return (
    <Panel title="Add a source">
      <FormRow label="Provider">
        {(field) => (
          <Select
            id={field.id}
            value={provider}
            onValueChange={(next) => setProvider(next as CalendarSourceBody["provider"])}
            options={[...PROVIDERS]}
          />
        )}
      </FormRow>
      <FormRow label="Name" hint="What to call this source in the sources table.">
        {(field) => (
          <Input
            id={field.id}
            describedBy={field.describedBy}
            value={displayName}
            onValueChange={setDisplayName}
            placeholder="Timetable"
          />
        )}
      </FormRow>
      <FormRow
        label="Address"
        hint={HINT_BY_PROVIDER[provider]}
        error={write.problem === null ? undefined : write.problem.detail}
      >
        {(field) => (
          <Input
            id={field.id}
            describedBy={field.describedBy}
            value={externalId}
            onValueChange={setExternalId}
            isInvalid={write.problem !== null}
            placeholder="https://example.edu/timetable.ics"
          />
        )}
      </FormRow>
      <div>
        <Button onClick={() => void add()}>Add source</Button>
      </div>
    </Panel>
  );
}
