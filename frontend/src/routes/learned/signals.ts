/* The five signal sources, what each yields, and which parameter it drives.
 *
 * `US-LEARN-06`, and it is a table because the reader's question is "what do my actions teach it" rather than "how
 * much has been learned". Section 11 states the same five rows, and this is the screen's rendering of them.
 *
 * THE WORDS ARE THE CLIENT'S HERE, DELIBERATELY, and it is the one place on this screen where they are. Every
 * figure and every claim about a parameter comes from the api, because the CLI and the screen must not describe
 * one week two ways. This table is not about the data at all: it is a fixed statement of how the product learns,
 * with no figure in it and no second renderer to disagree with. Serving it would make a static paragraph a
 * request.
 *
 * THE WHOLE-PLAN REJECTION IS A ROW, AND THAT IS THE POINT OF THE TABLE. A reader who thinks rejecting a week
 * teaches syncr something needs to be told that it yields almost nothing and why partial rejection exists
 * instead. Leaving it out would leave the four rows reading as encouragement. */

export interface SignalSource {
  /** The act, in the reader's own terms. */
  readonly source: string;
  /** What it yields as training signal. */
  readonly yields: string;
  /** Which parameter it drives, or what nothing means. */
  readonly drives: string;
}

export const SIGNAL_SOURCES: readonly SignalSource[] = [
  {
    source: "Every pin you make",
    yields:
      "A pairwise preference in a known context: you chose 13:00 over the proposed 06:00, " +
      "on a Tuesday, with those anchors already in the day.",
    drives: "The seven objective term weights, by learning to rank",
  },
  {
    source: "A partial outcome with actual minutes",
    yields: "An estimate error: what you planned against what it took.",
    drives: "The duration multiplier for that Area",
  },
  {
    source: "A skip you confirmed, with its timestamp",
    yields: "A refusal at a time of day.",
    drives: "The skip probability for that Area and time bucket",
  },
  {
    source: "A moved block, done at a different hour",
    yields:
      "A weaker signal than a pin: you did the work at another time without saying why, so it " +
      "is an observation rather than a labelled comparison.",
    drives:
      "The time-of-day fitness curve for the actual hour, and the planned bucket's skip probability",
  },
  {
    source: "Rejecting a whole week",
    yields:
      "One bit, with no credit assignment. Nothing in it says which of twenty blocks was wrong.",
    drives: "Almost nothing, which is why you can reject part of a proposal instead",
  },
];
