/* The calendar sources: what syncr reads, the one calendar it writes, and the six writes over them.
 *
 * An anchor type may scope its match rule to one source, and the rule then reads `source = Timetable`
 * rather than `source = 0f2c…`: an identifier in that cell would make the rules table unreadable
 * exactly where a reader is deciding which rule fires first. That read is why this file existed first.
 *
 * THE WRITES BELONG TO SETTINGS, AND SO DO THEY. Sources are declared, included, excluded, removed,
 * synced, given the write-target role and given a horizon on one screen, so the calls sit beside the
 * read they change rather than in a second file a reader has to find.
 *
 * THE GOOGLE CONNECTION IS A SECOND RESOURCE, not a field of the list. It carries the write-target
 * expiry notices, which the api composes: the words a reader acts on are written once, on the server,
 * so the banner in the top bar and the panel on Settings cannot state the outage differently. A
 * reconnect changes this resource and not the list, and including a source changes the list and not
 * this, which is why the two hold separate keys.
 *
 * EVERY WRITE INVALIDATES BY EXPLICIT KEY. A sync changes an anchor count, so it names the source
 * list; taking the write-target role changes which source carries `writeTarget`, so it names the same
 * list and nothing else. A blanket revalidation here would refetch the week because a feed was
 * excluded. */

import useSWR, { useSWRConfig } from "swr";
import { useState } from "react";

import { client } from "../client";
import { calendarSourcesKey, googleConnectionKey } from "../keys";
import { answered, apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type CalendarSource = components["schemas"]["CalendarSourceResponse"];
export type CalendarSourceBody = components["schemas"]["AddCalendarSourceRequest"];
export type GoogleConnection = components["schemas"]["GoogleConnectionResponse"];
export type GoogleConsent = components["schemas"]["GoogleConsentResponse"];

/** Whether a source contributes anchors. An excluded source reports zero and is not an error. */
export interface SourceInclusion {
  readonly sourceId: string;
  readonly included: boolean;
}

export interface SourceReference {
  readonly sourceId: string;
}

/** How many days ahead the plan is written. Write-target only; an anchor source is a stated 422. */
export interface HorizonEdit {
  readonly sourceId: string;
  readonly horizonDays: number;
}

async function readCalendarSources(): Promise<readonly CalendarSource[]> {
  const { sources } = await read(() => client.GET("/api/v1/calendar-sources"));
  return sources;
}

async function readGoogleConnection(): Promise<GoogleConnection> {
  return read(() => client.GET("/api/v1/calendar-sources/google/connection"));
}

export function useCalendarSources(): Resource<readonly CalendarSource[]> {
  return toResource(
    useSWR<readonly CalendarSource[], Problem>(calendarSourcesKey(), readCalendarSources),
  );
}

/** The connected account, and every notice its state raises at either volume. */
export function useGoogleConnection(): Resource<GoogleConnection> {
  return toResource(useSWR<GoogleConnection, Problem>(googleConnectionKey(), readGoogleConnection));
}

export function useSourceAddition(): Write<CalendarSourceBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: CalendarSourceBody) => {
    const refusal = await apply(() => client.POST("/api/v1/calendar-sources", { body }));
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

export function useSourceInclusion(): Write<SourceInclusion> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ sourceId, included }: SourceInclusion) => {
    const refusal = await apply(() =>
      client.PATCH("/api/v1/calendar-sources/{source_id}", {
        params: { path: { source_id: sourceId } },
        body: { included },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

export function useSourceRemoval(): Write<SourceReference> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ sourceId }: SourceReference) => {
    const refusal = await apply(() =>
      client.DELETE("/api/v1/calendar-sources/{source_id}", {
        params: { path: { source_id: sourceId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

/** Forcing a sync. The operation it answers with is followed by the count in the table changing. */
export function useSourceSync(): Write<SourceReference> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ sourceId }: SourceReference) => {
    const refusal = await apply(() =>
      client.POST("/api/v1/calendar-sources/{source_id}/sync", {
        params: { path: { source_id: sourceId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

/** Designating the one calendar syncr writes to. A second designation is a stated 409. */
export function useWriteTargetRole(): Write<SourceReference> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ sourceId }: SourceReference) => {
    const refusal = await apply(() =>
      client.PUT("/api/v1/calendar-sources/{source_id}/role", {
        params: { path: { source_id: sourceId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

export function useHorizonEdit(): Write<HorizonEdit> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ sourceId, horizonDays }: HorizonEdit) => {
    const refusal = await apply(() =>
      client.PATCH("/api/v1/calendar-sources/{source_id}/horizon", {
        params: { path: { source_id: sourceId } },
        body: { horizonDays },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(calendarSourcesKey());
    return null;
  });
}

/** The consent surface, once it has been asked for, and the refusal that came instead. */
export interface ConsentRequest {
  /** Asks the api for the consent surface. Answers with it, or null when the request was refused. */
  readonly begin: () => Promise<GoogleConsent | null>;
  readonly consent: GoogleConsent | null;
  readonly problem: Problem | null;
}

/**
 * Asking for the Google consent surface: the scopes, the calendars that will be read, and the URL.
 *
 * NOT A READ, BECAUSE ASKING FOR IT MINTS STATE. The api signs a state parameter bound to this tenant and expires
 * it, so a hook that fetched this on render would mint one every time a reader opened Settings. It is requested
 * when a reader asks to connect.
 *
 * IT ANSWERS WITH THE URL RATHER THAN NAVIGATING. US-CAL-02 requires the flow to name the scopes and the calendars
 * it will read, so the surface is rendered first and the reader follows a real link: an anchor with an href keeps
 * middle-click, cmd-click and the browser's own affordances, which a handler assigning `location` keeps none of.
 */
export function useGoogleConsent(): ConsentRequest {
  const [consent, setConsent] = useState<GoogleConsent | null>(null);
  const [problem, setProblem] = useState<Problem | null>(null);

  const begin = async (): Promise<GoogleConsent | null> => {
    /* `answered` rather than `apply`, because this is the one write on this screen whose own RESPONSE is what the
       caller renders: `apply` drops the body, and asking for it again would mint a second state parameter. */
    const { body, problem: refusal } = await answered(() =>
      client.POST("/api/v1/calendar-sources/google/connect"),
    );
    setProblem(refusal);
    setConsent(body);
    return body;
  };

  return { begin, consent, problem };
}
