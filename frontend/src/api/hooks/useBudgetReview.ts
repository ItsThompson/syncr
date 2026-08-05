/* The pie review: one quarter's behaviour against its budget, and the revision it proposes.
 *
 * ONE READ FEEDS BOTH OF THE AREAS SCREEN'S MODES, and that is deliberate rather than convenient. The
 * screen's composition and its deviation rows are the named week's; the review mode adds the trend and the
 * proposal from the same payload. Two reads would let the pie and the trend disagree about the same week,
 * which is the exact failure the week view's one-request rule exists to prevent one screen over.
 *
 * A NULL `discretionaryMinutes` IS AN ANSWER, NOT A FAILURE. The api reports no denominator for a week that
 * holds no plan of record, and `statement` says so, because a week nobody planned has no discretionary time
 * to divide. The screen renders that statement rather than a pie of one wedge.
 *
 * APPLYING A REVISION CHANGES EVERY AREA'S TARGET, so it invalidates the Area list and this review by
 * explicit key. A blanket revalidation would refetch the week on a screen that did not change it. */

import useSWR, { useSWRConfig } from "swr";

import { client } from "../client";
import { areasKey, budgetReviewKey } from "../keys";
import { apply, read } from "./request";
import { useWrite, type Write } from "./useWrite";
import { toResource, type Problem, type Resource } from "../../contract";
import type { components } from "../schema";

export type BudgetReview = components["schemas"]["BudgetReviewResponse"];
export type ReviewCategory = components["schemas"]["CategoryReadingResponse"];
export type ReviewDayCounts = components["schemas"]["ReviewDayCounts"];
export type ReviewTrendWeek = components["schemas"]["TrendWeekResponse"];
export type BudgetProposal = components["schemas"]["BudgetProposalResponse"];
export type ProposedShare = components["schemas"]["ProposedShareResponse"];
export type BudgetRevisionBody = components["schemas"]["BudgetApplyRequest"];

async function readBudgetReview(period: string): Promise<BudgetReview> {
  return read(() => client.GET("/api/v1/reviews/budget", { params: { query: { period } } }));
}

/** The quarter's review, anchored at `period`, which is an ISO week such as `2026-W07`. */
export function useBudgetReview(period: string): Resource<BudgetReview> {
  return toResource(
    useSWR<BudgetReview, Problem>(budgetReviewKey(period), () => readBudgetReview(period)),
  );
}

/**
 * Declaring the shares a review proposed, whole or adjusted.
 *
 * One path for both, so an adjusted revision cannot take a route a whole one does not. Two keys are named
 * rather than a blanket revalidation: a revision moves every Area's target and this review's figures, and
 * nothing else on any screen.
 */
export function useBudgetRevision(period: string): Write<BudgetRevisionBody> {
  const { mutate } = useSWRConfig();

  return useWrite(async (body: BudgetRevisionBody) => {
    const refusal = await apply(() => client.POST("/api/v1/reviews/budget/apply", { body }));
    if (refusal !== null) return refusal;
    await mutate(areasKey());
    await mutate(budgetReviewKey(period));
    return null;
  });
}
