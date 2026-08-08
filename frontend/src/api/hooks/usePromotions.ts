/* ACCEPTING OR DECLINING A REPEATED PIN, which is the only pair of writes the weekly session owns beyond its pins.
 *
 * NEITHER TAKES A BODY. Everything a promotion states is in its identifier, which the session's payload carries: the
 * kind, the content, the weekday and the minute of the day. A body would be a second place the same four values could
 * be sent.
 *
 * ACCEPTING CHANGES A DAY SHAPE, SO IT INVALIDATES THE DAY SHAPES. It also changes what the week solves against, which
 * is why the week and the session are named too: the session's raises are derived from the plan beside them, and a
 * template edit bumps the input version of this week onward.
 *
 * DECLINING CHANGES ONLY WHAT IS ASKED. No template moves and no week is re-solved, so the session's own payload is
 * the one thing that has to be read again: the candidate it raised is silenced.
 *
 * THE TWO WRITES ARE TWO HOOKS RATHER THAN ONE WITH A MODE, because they invalidate different things and mean
 * different acts. A caller that had to pass `"accept"` would be one branch away from declining by accident. */

import { useSWRConfig } from "swr";

import { client } from "../client";
import { dayShapesKey, weekKey, weeklySessionKey } from "../keys";
import { apply } from "./request";
import { useWrite, type Write } from "./useWrite";
import type { components } from "../schema";

export type PromotionAccepted = components["schemas"]["PromotionAcceptedResponse"];
export type PromotionDeclined = components["schemas"]["PromotionDeclinedResponse"];

/** Which pattern is being answered. The identifier is the session payload's own. */
export interface PromotionBody {
  readonly promotionId: string;
}

/** Absorbing the pattern: the day-shape entry it names moves to the time it keeps being pinned to. */
export function usePromotionAccept(isoWeek: string): Write<PromotionBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ promotionId }: PromotionBody) => {
    const refusal = await apply(() =>
      client.POST("/api/v1/promotions/{promotion_id}/accept", {
        params: { path: { promotion_id: promotionId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(dayShapesKey());
    await mutate(weeklySessionKey(isoWeek));
    await mutate(weekKey(isoWeek));
    return null;
  });
}

/** Answering the question instead: nothing is applied, and it is not asked again for a while. */
export function usePromotionDecline(isoWeek: string): Write<PromotionBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async ({ promotionId }: PromotionBody) => {
    const refusal = await apply(() =>
      client.POST("/api/v1/promotions/{promotion_id}/decline", {
        params: { path: { promotion_id: promotionId } },
      }),
    );
    if (refusal !== null) return refusal;
    await mutate(weeklySessionKey(isoWeek));
    return null;
  });
}
