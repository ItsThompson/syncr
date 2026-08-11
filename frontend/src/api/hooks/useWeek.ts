/* THE WEEK SCREEN'S WHOLE READ, IN ONE REQUEST.
 *
 * Composing it client-side would risk a strip figure disagreeing with the same figure in a review, which is exactly
 * what the composed endpoint exists to prevent: `readings` is computed server-side from one arithmetic over one
 * occupancy read, so the strip and the pie review cannot answer one question differently.
 *
 * `live` IS NULLABLE, and that is what makes the planning horizon a visible product concept rather than an invisible
 * assumption. A read never triggers work, so a week beyond the horizon has no plan by design, and `emptyReason` says
 * which of the two reasons it is while `emptyWeek` carries the facts the screen's actions need.
 *
 * A SOLVE IS A REQUEST RATHER THAN A RESULT. It answers with the operation it created or found, and it is idempotent
 * per week without a key, so a second press hands back the same operation rather than queueing a second one. The
 * week's own key is invalidated on the way out, because the operation the response carries is a field of the view.
 *
 * THE PAYLOAD'S TYPE IS THE ONE THE CLIENT HANDS BACK rather than the schema's own name for it, because the two are
 * not the same type in general. A field whose type is exactly `null` does not survive the generated client's response
 * mapping, since an absent key is what `openapi-fetch` maps `null` to, so naming `WeekViewResponse` can type a hook
 * against a field no caller can read. Deriving the type from the call is true whatever the document declares, and
 * `lint:contract` is what holds the difference at zero rather than merely at zero today. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { weekKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";

async function readWeek(isoWeek: string) {
  return read(() =>
    client.GET("/api/v1/weeks/{iso_week}", { params: { path: { iso_week: isoWeek } } }),
  );
}

/** The Week screen's whole read, as the generated client answers with it. */
export type WeekView = Awaited<ReturnType<typeof readWeek>>;

/** The plan of record for a week. Read through `WeekView`, because that is the only route that answers with one. */
export type PlanDocument = NonNullable<WeekView["live"]>;
export type WeekReadings = NonNullable<WeekView["readings"]>;
export type EmptyWeekFacts = NonNullable<WeekView["emptyWeek"]>;

/** A solve names its week in the path, so the identifier arrives with the call rather than with the hook. */
export interface SolveRequest {
  readonly isoWeek: string;
  /** Bypasses the debounce, which is what the "solve this week now" action needs. */
  readonly isImmediate?: boolean | undefined;
}

export function useWeek(isoWeek: string): Resource<WeekView> {
  return toResource(useSWR<WeekView, Problem>(weekKey(isoWeek), () => readWeek(isoWeek)));
}

export function useWeekSolve(): Write<SolveRequest> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ isoWeek, isImmediate }: SolveRequest) => {
    const refusal = await apply(() =>
      client.POST("/api/v1/weeks/{iso_week}/solve", {
        params: {
          path: { iso_week: isoWeek },
          query: isImmediate === true ? { immediate: true } : {},
        },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(weekKey(isoWeek));
    return null;
  });
}
