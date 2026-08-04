/* The calendar sources, read for their names alone.
 *
 * An anchor type may scope its match rule to one source, and the rule then reads `source = Timetable`
 * rather than `source = 0f2c…`: an identifier in that cell would make the rules table unreadable
 * exactly where a reader is deciding which rule fires first. Sources are declared on Settings, so
 * nothing here creates, edits or removes one. */

import useSWR from "swr";

import { client } from "../client";
import { calendarSourcesKey } from "../keys";
import { read } from "./request";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type CalendarSource = components["schemas"]["CalendarSourceResponse"];

async function readCalendarSources(): Promise<readonly CalendarSource[]> {
  const { sources } = await read(() => client.GET("/api/v1/calendar-sources"));
  return sources;
}

export function useCalendarSources(): Resource<readonly CalendarSource[]> {
  return toResource(
    useSWR<readonly CalendarSource[], Problem>(calendarSourcesKey(), readCalendarSources),
  );
}
