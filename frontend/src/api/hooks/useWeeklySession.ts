/* THE WEEKLY SESSION'S ONE READ: last week's retrospective, next week's raises, and the verdict.
 *
 * ONE REQUEST FOR BOTH HALVES, which is what `US-REV-01`'s "planning and retrospective in one pass" means on the wire.
 * The week the payload is addressed by is the week being PLANNED and the retrospective covers the week before it, so a
 * reader does not choose a second period and two halves cannot report different weeks.
 *
 * THE VERDICT ON THIS PAYLOAD IS THE WEEK VIEW'S OWN, computed server-side through the same collaborator. So the mode
 * renders the verdict panel from the week's read rather than from this one: two panels drawn from two payloads read a
 * request apart would disagree the moment a solve landed between them. What this read is for is the retrospective, the
 * raised items and the promotion candidates, none of which the week view carries.
 *
 * A NULL VERDICT IS AN ANSWER. The api reports none for a week that holds no plan, and `statement` says so, because
 * nothing has been computed about such a week. The mode renders that sentence rather than an empty panel. */

import useSWR from "swr";

import { client } from "../client";
import { weeklySessionKey } from "../keys";
import { read } from "./request";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type WeeklySession = components["schemas"]["WeeklySessionResponse"];
export type SessionRetro = components["schemas"]["SessionRetroResponse"];
export type RaisedItem = components["schemas"]["RaisedItemResponse"];
export type RaisedKind = components["schemas"]["RaisedKind"];
export type PromotionCandidate = components["schemas"]["PromotionCandidateResponse"];

async function readWeeklySession(isoWeek: string): Promise<WeeklySession> {
  return read(() =>
    client.GET("/api/v1/reviews/week/{iso_week}", { params: { path: { iso_week: isoWeek } } }),
  );
}

/**
 * The session for the week `isoWeek` plans, reviewing the week before it.
 *
 * `isSession` gates the read, because the payload costs a week assembly and the retrospective's own quarter: a screen
 * that is not in the mode must not pay for it. SWR reads nothing for a null key, which is how that gate is expressed
 * without a second code path.
 */
export function useWeeklySession(
  isoWeek: string,
  isSession: boolean,
): Resource<WeeklySession> | null {
  const reading = useSWR<WeeklySession, Problem>(
    isSession && isoWeek !== "" ? weeklySessionKey(isoWeek) : null,
    () => readWeeklySession(isoWeek),
  );
  return isSession ? toResource(reading) : null;
}
