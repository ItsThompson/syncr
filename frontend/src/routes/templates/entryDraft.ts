/* The entry editor's draft, and the two request bodies it can become.
 *
 * THE PAIRING RULE IS THE SHAPE, ON BOTH SIDES. The api declares an entry as one of two bodies: a concrete
 * entry cannot omit its binding, and a slot has nowhere to put one. So this module does not build a body with
 * optional members and hope: it answers `declarable` with the body for the kind, or `incomplete` naming the
 * member the reader still has to choose. The form then refuses the submit rather than sending a request the
 * boundary will refuse, which is the difference between a control that states a rule and one that discovers it.
 *
 * A CONCRETE ENTRY DOES NOT OFFER THE AREA HERE, though the api accepts one. On a concrete entry the Area is a
 * statement about which budget the time reports to, and the routine or habit it names already says what
 * happens; offering both controls in one form is what makes an Area-only body look declarable. Reporting
 * attribution is an Area's own question and this form leaves it there.
 *
 * Pure: no React, no client, no DOM. Every case below is a literal in a test. */

import type { BindingChoice } from "./bindings";
import type { EntryBody } from "../../api/hooks/useTemplates";

export type EntryKind = "concrete" | "slot";

export interface EntryDraft {
  readonly kind: EntryKind;
  /** `HH:MM` wall time, which the api holds to the quarter hour. */
  readonly targetTime: string;
  readonly durationMinutes: number;
  readonly flexBandMinutes: number;
  /** The routine or habit a concrete entry names, or null while none is chosen. */
  readonly binding: BindingChoice | null;
  /** The Area a slot reserves time for, or null while none is chosen. */
  readonly areaId: string | null;
}

/** Which control an incomplete draft is missing, so the form can put the message on that row. */
export type EntryMember = "binding" | "area";

export type EntryProposal =
  | { readonly status: "declarable"; readonly body: EntryBody }
  | { readonly status: "incomplete"; readonly member: EntryMember; readonly reason: string };

/* An hour at 07:00 is the shape of the rendered sheet's first slot. A band of zero is the api's own default:
 * a band is a permission to shift, so declaring none is declaring the target time and nothing else. */
export const EMPTY_ENTRY_DRAFT: EntryDraft = {
  kind: "concrete",
  targetTime: "07:00",
  durationMinutes: 60,
  flexBandMinutes: 0,
  binding: null,
  areaId: null,
};

export function entryProposalFrom(draft: EntryDraft): EntryProposal {
  const span = {
    targetTime: draft.targetTime,
    durationMinutes: draft.durationMinutes,
    flexBandMinutes: draft.flexBandMinutes,
  };

  if (draft.kind === "slot") {
    if (draft.areaId === null) {
      return {
        status: "incomplete",
        member: "area",
        reason:
          "A slot reserves time for one Area. Choose the Area whose budget this time reports to, or " +
          "declare a concrete entry naming what happens.",
      };
    }
    return { status: "declarable", body: { kind: "slot", ...span, areaId: draft.areaId } };
  }

  if (draft.binding === null) {
    return {
      status: "incomplete",
      member: "binding",
      reason:
        "A concrete entry names the routine or habit that happens. Choose one, or declare a slot and " +
        "let the plan bind the content.",
    };
  }
  return {
    status: "declarable",
    body: {
      kind: "concrete",
      ...span,
      bindingTarget: draft.binding.target,
      bindingRef: draft.binding.ref,
    },
  };
}
