/* The retry policy for every unsafe request the browser sends.
 *
 * A guarded route receives a key so one user gesture cannot become two writes after a retry. A route
 * with no guard is named instead of being silently treated as safe. Add a policy row before adding a
 * new unsafe client call. */

export type UnsafeClientMethod = "POST" | "PUT" | "PATCH" | "DELETE";

interface GuardedCall {
  readonly classification: "guarded";
}

interface ExemptCall {
  readonly classification: "exempt";
  readonly reason: string;
}

export interface UnsafeClientCallPolicy {
  readonly method: UnsafeClientMethod;
  readonly route: string;
  readonly policy: GuardedCall | ExemptCall;
}

const EXEMPT: ExemptCall = { classification: "exempt", reason: "the route carries no guard" };
const GUARDED: GuardedCall = { classification: "guarded" };

export const UNSAFE_CLIENT_CALL_POLICIES: readonly UnsafeClientCallPolicy[] = [
  { method: "PATCH", route: "/api/v1/anchor-types/{anchor_type_id}", policy: EXEMPT },
  { method: "PUT", route: "/api/v1/anchor-types/order", policy: EXEMPT },
  { method: "POST", route: "/api/v1/areas", policy: EXEMPT },
  { method: "POST", route: "/api/v1/calendar-sources", policy: GUARDED },
  { method: "DELETE", route: "/api/v1/calendar-sources/{source_id}", policy: EXEMPT },
  { method: "PATCH", route: "/api/v1/calendar-sources/{source_id}", policy: EXEMPT },
  { method: "PATCH", route: "/api/v1/calendar-sources/{source_id}/horizon", policy: EXEMPT },
  { method: "PUT", route: "/api/v1/calendar-sources/{source_id}/role", policy: EXEMPT },
  { method: "POST", route: "/api/v1/calendar-sources/{source_id}/sync", policy: GUARDED },
  { method: "POST", route: "/api/v1/calendar-sources/google/connect", policy: EXEMPT },
  { method: "PUT", route: "/api/v1/areas/{area_id}/preference", policy: GUARDED },
  { method: "DELETE", route: "/api/v1/areas/{area_id}/preference", policy: GUARDED },
  { method: "PUT", route: "/api/v1/blocks/{block_id}/outcome", policy: GUARDED },
  { method: "POST", route: "/api/v1/conflicts/{conflict_id}/resolve", policy: GUARDED },
  { method: "POST", route: "/api/v1/days/{date}/confirm", policy: GUARDED },
  { method: "POST", route: "/api/v1/days/confirm-range", policy: GUARDED },
  { method: "PATCH", route: "/api/v1/habits/{habit_id}", policy: GUARDED },
  { method: "POST", route: "/api/v1/off-plan", policy: GUARDED },
  { method: "DELETE", route: "/api/v1/off-plan/{period_id}", policy: GUARDED },
  { method: "PATCH", route: "/api/v1/off-plan/{period_id}", policy: GUARDED },
  { method: "POST", route: "/api/v1/promotions/{promotion_id}/accept", policy: EXEMPT },
  { method: "POST", route: "/api/v1/promotions/{promotion_id}/decline", policy: EXEMPT },
  { method: "POST", route: "/api/v1/reviews/budget/apply", policy: EXEMPT },
  { method: "PATCH", route: "/api/v1/routines/{routine_id}", policy: GUARDED },
  { method: "PATCH", route: "/api/v1/settings", policy: EXEMPT },
  { method: "POST", route: "/api/v1/settings/travel-overrides", policy: EXEMPT },
  { method: "DELETE", route: "/api/v1/settings/travel-overrides/{override_id}", policy: EXEMPT },
  { method: "POST", route: "/api/v1/tasks", policy: GUARDED },
  { method: "PUT", route: "/api/v1/tasks/{task_id}/preference", policy: GUARDED },
  { method: "POST", route: "/api/v1/tasks/{task_id}/complete", policy: GUARDED },
  { method: "POST", route: "/api/v1/templates/{template_id}/entries", policy: GUARDED },
  { method: "POST", route: "/api/v1/weight-sets/{version}/activate", policy: GUARDED },
  { method: "PUT", route: "/api/v1/week-pattern", policy: GUARDED },
  { method: "POST", route: "/api/v1/weeks/{iso_week}/approve", policy: GUARDED },
  { method: "POST", route: "/api/v1/weeks/{iso_week}/pins", policy: GUARDED },
  { method: "DELETE", route: "/api/v1/weeks/{iso_week}/pins/{pin_id}", policy: GUARDED },
  { method: "POST", route: "/api/v1/weeks/{iso_week}/reject-block", policy: GUARDED },
  { method: "POST", route: "/api/v1/weeks/{iso_week}/solve", policy: EXEMPT },
  { method: "POST", route: "/api/v1/weeks/{iso_week}/tradeoffs", policy: EXEMPT },
];

export function policyForUnsafeClientCall(
  method: UnsafeClientMethod,
  route: string,
): UnsafeClientCallPolicy | undefined {
  return UNSAFE_CLIENT_CALL_POLICIES.find(
    (candidate) => candidate.method === method && candidate.route === route,
  );
}
