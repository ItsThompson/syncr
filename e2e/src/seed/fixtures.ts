/* The fixture registry: the scenarios' fixture table, as the recipes that load it.
 *
 * One name per fixture the scenarios name, spelled the way the scenario table spells it, so a
 * scenario naming a fixture and this harness loading one are naming the same thing.
 * `hand_tuned_weights` is absent deliberately: the bootstrap provisions weight set version 1 with
 * `origin = "hand-tuned"`, so it is not a fixture this harness loads but a fact of every tenant it
 * creates. `hostile_ics` is absent for the same kind of reason: it is a corpus of feed bodies the
 * api's own adapter suite reads, and nothing in a browser can observe a parse.
 *
 * `tight_capacity`, `owes_more_than_a_week` and `repeated_pins` are the three names this harness
 * added rather than inherited. `tight_capacity` exists for a week whose verdict one mutation can
 * move, which is what makes the floor reservation, the progress arithmetic and a session-attributed
 * infeasibility episode observable at all: three of this suite's stated gaps had one cause, and it
 * was the absence of this week. `owes_more_than_a_week` is a week with no frame and a gap no week
 * could close, which is what makes the span a verdict measures capacity over readable as a figure
 * rather than as a comparison. `repeated_pins` is the reference week plus one content pinned to one
 * local time in three consecutive weeks beyond it, because no fixture that only materializes the
 * horizon can hold pins in three future weeks and so raise the promotion candidate the panel reads.
 */

import type { ApiClient } from "../api/client.ts";
import { seedDstWeeks } from "./fixtures/dst-weeks.ts";
import { seedElasticSleep } from "./fixtures/elastic-sleep.ts";
import { seedMaturityCorpus } from "./fixtures/maturity-corpus.ts";
import { seedOffPlanWeek } from "./fixtures/off-plan-week.ts";
import { seedOwesMoreThanAWeek } from "./fixtures/owes-more-than-a-week.ts";
import { seedPartialProgress } from "./fixtures/partial-progress.ts";
import { seedRecoveryScopes } from "./fixtures/recovery-scopes.ts";
import { seedRepeatedPins } from "./fixtures/repeated-pins.ts";
import { seedReferenceWeek } from "./fixtures/reference-week.ts";
import { seedShadowGeometry } from "./fixtures/shadow-geometry.ts";
import { seedTightCapacity } from "./fixtures/tight-capacity.ts";

export type Fixture = (client: ApiClient) => Promise<void>;

export const FIXTURES: Readonly<Record<string, Fixture>> = {
  reference_week: seedReferenceWeek,
  dst_weeks: seedDstWeeks,
  off_plan_week: seedOffPlanWeek,
  elastic_sleep: seedElasticSleep,
  partial_progress: seedPartialProgress,
  recovery_scopes: seedRecoveryScopes,
  shadow_geometry: seedShadowGeometry,
  maturity_corpus: seedMaturityCorpus,
  tight_capacity: seedTightCapacity,
  owes_more_than_a_week: seedOwesMoreThanAWeek,
  repeated_pins: seedRepeatedPins,
};

export const fixtureNames = (): readonly string[] => Object.keys(FIXTURES);
