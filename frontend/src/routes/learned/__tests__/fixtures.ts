/* The Learned screen's fixtures, shaped as the api sends them.
 *
 * EVERY DEFAULT IS A SHAPE THE API CAN PRODUCE. A collecting row carries no value and a ready row carries one,
 * because the api refuses a row whose state disagrees with its own figure: that is the gate as the reader sees it,
 * and a fixture that broke it would prove the screen against something production cannot send.
 *
 * THE THREE STATEMENTS BELOW ARE STAND-INS FOR THE API'S SHAPE, NOT ITS WORDS. Each is a sentence of the right
 * kind in the right field, and none is the served string: measured against a running api, all three differ. That
 * is deliberate and it is what the cases rest on -- they assert that the SERVED value reaches the screen, so a
 * fixture holding the real wording would let a screen that hard-coded the sentence pass. Quoting the api here
 * would also be a copy that goes stale the first time the api's copy is edited. */

import type {
  Learned,
  LearnedParameter,
  WeightSet,
  WeightSets,
} from "../../../api/hooks/useLearned";

export const FITNESS = "11111111-1111-4111-8111-111111111111";

export const COLLECTING_IS_NORMAL =
  "Nothing is broken while a parameter collects. syncr applies a number only once it has enough " +
  "confirmed evidence to be worth trusting, and until then it uses the hand-tuned one.";
export const UNLOCKS_COUNT_VOLUME =
  "Progress counts confirmed days and observations, never how much of the plan you followed. A day " +
  "where you skipped everything and said so advances every count exactly as much as a perfect day.";
export const THRESHOLDS_ARE_ESTIMATES =
  "The sample counts each parameter needs are unvalidated estimates rather than measurements. They " +
  "are configuration and will be revised against real data.";

/** A parameter the solver is applying: at or above its gate, so it carries a figure. */
export function buildReadyParameter(overrides: Partial<LearnedParameter> = {}): LearnedParameter {
  return {
    parameter: `duration_multiplier[${FITNESS}]`,
    subject: "Fitness",
    samples: 14,
    threshold: 12,
    state: "ready",
    value: 1.2,
    shrinkageWeight: 0.42,
    plainLanguage:
      "You estimate 60m for Fitness; your actual median is 82m, which is longer than planned, so " +
      "estimates here are scaled by 1.20.",
    ...overrides,
  };
}

/** A parameter below its gate: not applied at all, so it carries no figure. */
export function buildCollectingParameter(
  overrides: Partial<LearnedParameter> = {},
): LearnedParameter {
  return buildReadyParameter({
    parameter: "objective_weights",
    /* The subject is the Area the parameter's KEY names, and this parameter is fitted once for the whole
     * account: a keyless parameter with a subject is a row the api cannot send. */
    subject: null,
    samples: 0,
    threshold: 50,
    state: "collecting",
    value: null,
    shrinkageWeight: 1,
    plainLanguage:
      "Your pins are the evidence for this one. 0 of 50 edits collected, so the hand-tuned weights " +
      "are still in force.",
    ...overrides,
  });
}

export function buildLearned(overrides: Partial<Learned> = {}): Learned {
  const parameters = overrides.parameters ?? [buildReadyParameter(), buildCollectingParameter()];
  return {
    version: 1,
    origin: "hand-tuned",
    fittedAt: null,
    ready: parameters.filter((row) => row.state === "ready").length,
    collecting: parameters.filter((row) => row.state === "collecting").length,
    thresholdsAreEstimates: THRESHOLDS_ARE_ESTIMATES,
    unlocksCountConfirmedVolume: UNLOCKS_COUNT_VOLUME,
    collectingIsNormal: COLLECTING_IS_NORMAL,
    ...overrides,
    parameters,
  };
}

/** What a fresh account reads: version 1 in force, hand-tuned, and no parameter fitted at all. */
export function buildCollectingBaseline(): Learned {
  return buildLearned({ parameters: [], ready: 0, collecting: 0 });
}

/** The one version a first account holds: hand-tuned, in force, and never fitted. */
export const ONLY_HAND_TUNED: WeightSet = {
  version: 1,
  origin: "hand-tuned",
  active: true,
  fittedAt: null,
  createdAt: "2026-01-05T09:00:00+00:00",
  ready: 0,
  collecting: 0,
};

export function buildWeightSets(overrides: Partial<WeightSets> = {}): WeightSets {
  return {
    versions: [
      {
        version: 2,
        origin: "fitted",
        active: false,
        fittedAt: "2026-02-16T03:00:00+00:00",
        createdAt: "2026-02-16T03:00:00+00:00",
        ready: 5,
        collecting: 1,
      },
      ONLY_HAND_TUNED,
    ],
    ...overrides,
  };
}
