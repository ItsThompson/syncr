/* The fixture registry: section 20's fixture table, as the recipes that load it.
 *
 * One name per row of that table, spelled exactly as the table spells it, so a scenario naming a
 * fixture and the spec naming one are naming the same thing. `hand_tuned_weights` is absent
 * deliberately: the bootstrap provisions weight set version 1 with `origin = "hand-tuned"`, so it is
 * not a fixture this harness loads but a fact of every tenant it creates. `hostile_ics` is absent for
 * the same kind of reason: it is a corpus of feed bodies the api's own adapter suite reads, and
 * nothing in a browser can observe a parse.
 */

import type { ApiClient } from "../api/client.ts";
import { seedDstWeeks } from "./fixtures/dst-weeks.ts";
import { seedElasticSleep } from "./fixtures/elastic-sleep.ts";
import { seedMaturityCorpus } from "./fixtures/maturity-corpus.ts";
import { seedOffPlanWeek } from "./fixtures/off-plan-week.ts";
import { seedPartialProgress } from "./fixtures/partial-progress.ts";
import { seedRecoveryScopes } from "./fixtures/recovery-scopes.ts";
import { seedReferenceWeek } from "./fixtures/reference-week.ts";
import { seedShadowGeometry } from "./fixtures/shadow-geometry.ts";

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
};

export const fixtureNames = (): readonly string[] => Object.keys(FIXTURES);
