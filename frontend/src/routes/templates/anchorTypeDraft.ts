/* The anchor-type editor's draft, and the patch body it becomes.
 *
 * WHERE THE LINE BETWEEN THIS FORM AND THE BOUNDARY SITS, stated once because it decides what belongs here.
 * The form refuses to send a draft that is INCOMPLETE: a member the reader has not chosen yet, such as a
 * recovery window scoped to named Areas with no Area named. It does NOT re-check the api's arithmetic. A prep
 * lead that leaves prep running when the outbound leg leaves is a rule over three chosen values, the api
 * states it with the member to change, and restating it here would be a second copy free to drift from the
 * one the table's own check constraint holds. That refusal is meant to be seen: it arrives as a 422 naming
 * the member, and the screen renders it inline in amber beside the control.
 *
 * THE PATCH CARRIES EVERY GEOMETRY MEMBER, not only the changed ones. Each is an absolute value, so a whole
 * body is idempotent and a reader who changed two members in one sitting does not get two requests. An
 * omitted member is left alone and an explicit null clears a nullable one, which is what `transitLeadMinutes`
 * needs: null is the abutting default, meaning leave exactly late enough to arrive on time.
 *
 * Pure: no React, no client, no DOM. */

import type { AnchorType, AnchorTypeEdit } from "../../api/hooks/useAnchorTypes";
import type { components } from "../../api/schema";

export type PostScope = components["schemas"]["PostScope"];

export interface AnchorTypeDraft {
  readonly prepLeadMinutes: number;
  readonly prepDurationMinutes: number;
  /** Null makes prep a forbidden window rather than a block, because a buffer with no Area has no budget. */
  readonly prepAreaId: string | null;
  /** Null abuts the commitment: leave exactly late enough to arrive on time. */
  readonly transitLeadMinutes: number | null;
  readonly transitDurationMinutes: number;
  readonly returnTransitMinutes: number;
  readonly transitAreaId: string | null;
  readonly postBufferMinutes: number;
  readonly postScope: PostScope;
  readonly forbiddenAreaIds: readonly string[];
}

export type AnchorTypeProposal =
  | { readonly status: "declarable"; readonly body: AnchorTypeEdit }
  | { readonly status: "incomplete"; readonly member: "forbiddenAreas"; readonly reason: string };

export function anchorTypeDraftFrom(type: AnchorType): AnchorTypeDraft {
  return {
    prepLeadMinutes: type.prepLeadMinutes,
    prepDurationMinutes: type.prepDurationMinutes,
    prepAreaId: type.prepAreaId,
    transitLeadMinutes: type.transitLeadMinutes,
    transitDurationMinutes: type.transitDurationMinutes,
    returnTransitMinutes: type.returnTransitMinutes,
    transitAreaId: type.transitAreaId,
    postBufferMinutes: type.postBufferMinutes,
    postScope: type.postScope,
    forbiddenAreaIds: type.forbiddenAreaIds,
  };
}

export function anchorTypeProposalFrom(draft: AnchorTypeDraft): AnchorTypeProposal {
  /* The list carries the members of the one scope that has members. An empty list once meant "forbids
   * everything", which reads as an oversight rather than as a decision, so the choice is stated on the scope
   * and the api holds the two to each other. */
  const forbiddenAreaIds = draft.postScope === "areas" ? [...draft.forbiddenAreaIds] : [];
  if (draft.postScope === "areas" && forbiddenAreaIds.length === 0) {
    return {
      status: "incomplete",
      member: "forbiddenAreas",
      reason:
        "A recovery window scoped to named Areas with none named would forbid nothing. Name at least " +
        "one Area, or set the scope to nothing or to everything.",
    };
  }

  return {
    status: "declarable",
    body: {
      prepLeadMinutes: draft.prepLeadMinutes,
      prepDurationMinutes: draft.prepDurationMinutes,
      prepAreaId: draft.prepAreaId,
      transitLeadMinutes: draft.transitLeadMinutes,
      transitDurationMinutes: draft.transitDurationMinutes,
      returnTransitMinutes: draft.returnTransitMinutes,
      transitAreaId: draft.transitAreaId,
      postBufferMinutes: draft.postBufferMinutes,
      postScope: draft.postScope,
      forbiddenAreaIds,
    },
  };
}
