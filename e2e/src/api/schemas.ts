/* The wire types, taken from the committed OpenAPI document rather than restated here.
 *
 * `frontend/src/api/schema.d.ts` is generated from `frontend/openapi.json`, which is generated from
 * the FastAPI app, and the `contract` CI job regenerates both and fails on a diff. Importing it is
 * therefore the one spelling of every response shape this suite reads: a field that moves breaks
 * the typecheck here in the same commit it breaks the frontend, rather than at the moment a
 * scenario reads `undefined` and asserts something vacuous about it.
 */

import type { components } from "../../../frontend/src/api/schema";

type Schemas = components["schemas"];

export type WeekView = Schemas["WeekViewResponse"];
export type Verdict = Schemas["VerdictResponse"];
export type Shortfall = Schemas["ShortfallResponse"];
export type ShortfallKind = Schemas["ShortfallKind"];
export type Tradeoff = Schemas["TradeoffResponse"];
export type Operation = Schemas["OperationResponse"];
export type OperationStatus = Schemas["OperationStatus"];
export type Operations = Schemas["OperationsResponse"];
export type PlanDocument = Schemas["PlanDocumentResponse"];
export type Block = Schemas["BlockResponse"];
export type EmptySlot = Schemas["EmptySlotResponse"];
export type EmptyWeek = Schemas["EmptyWeekResponse"];
export type ForbiddenWindow = Schemas["ForbiddenWindowResponse"];
export type Pin = Schemas["PinResponse"];
export type Conflict = Schemas["ConflictResponse"];
export type Conflicts = Schemas["ConflictsResponse"];
export type Adjustment = Schemas["AdjustmentResponse"];
export type PendingProposal = Schemas["PendingProposalResponse"];
export type WeekApproved = Schemas["WeekApprovedResponse"];
export type WeekRevisions = Schemas["WeekRevisionsResponse"];
export type WeekReadings = Schemas["WeekReadingsResponse"];
export type Day = Schemas["DayResponse"];
export type Task = Schemas["TaskResponse"];
export type Tasks = Schemas["TasksResponse"];
export type Areas = Schemas["AreasResponse"];
export type Budget = Schemas["BudgetResponse"];
export type CalendarSource = Schemas["CalendarSourceResponse"];
export type Anchors = Schemas["AnchorsResponse"];
export type Anchor = Schemas["AnchorResponse"];
export type Adjustments = Schemas["AdjustmentsResponse"];
