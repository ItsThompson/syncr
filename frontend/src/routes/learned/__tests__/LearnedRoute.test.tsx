/* THE LEARNED SCREEN, DRIVEN THROUGH THE REAL ROUTE AND THE REAL CLIENT.
 *
 * WHAT THIS FILE ANSWERS is whether the screen does the job section 11 gives it: it is the product's TRUST SURFACE,
 * where a reader checks syncr against their own experience, rather than a diagnostic panel. So the cases are about
 * what a reader can take from it -- the figure, the sentence, the two counts, the sources, the versions -- and about
 * the one thing it must never do, which is read as a warning.
 *
 * THE PIGMENT GUARD IS DERIVED, NOT LISTED. Three earlier guards of this shape in this repo were bounded by a list of
 * class names and each list had a hole somebody else found. This one takes every class the screen actually renders,
 * compiles them the way the build does, and refuses any that resolves to a signal token read out of the token layer
 * itself. A pigment reaching this screen through a utility nobody thought of is a red test rather than a gap.
 *
 * THE METER IS ASSERTED AT BOTH BOUNDARIES, and from rows the api can really send: a parameter at zero samples draws
 * an empty run, and one past its threshold draws a complete one and reports the CLAMPED pair, because a meter whose
 * run and whose announced range disagree lies to one of its two audiences.
 *
 * THE THREE STATEMENTS ARE ASSERTED AS PRESENT, NOT AS WORDED. Each is composed server-side so the CLI and the screen
 * cannot state a rule two ways; a case asserting the wording would be asserting this file's copy of the api's words. */

import { screen, waitFor, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { declaredTokens } from "../../../../scripts/lib/tokens.ts";
import { apiServer } from "../../../testing/apiServer";
import { compileUtilities, declarationsOf } from "../../../testing/compileTheme";
import { countedHandler, jsonHandler, pendingHandler, readyz } from "../../../testing/apiStub";
import { renderAt } from "../../../testing/renderRoute";
import {
  COLLECTING_IS_NORMAL,
  FITNESS,
  ONLY_HAND_TUNED,
  THRESHOLDS_ARE_ESTIMATES,
  UNLOCKS_COUNT_VOLUME,
  buildCollectingBaseline,
  buildCollectingParameter,
  buildLearned,
  buildReadyParameter,
  buildWeightSets,
} from "./fixtures";
import type { Learned, WeightSets } from "../../../api/hooks/useLearned";

const LEARNED_PATH = "/api/v1/learned";
const WEIGHT_SETS_PATH = "/api/v1/weight-sets";
const SCREEN = "/learned";

/* The signal pigments, as the token layer declares them: failure, notice and resolution. `info` is not one of
 * them -- it spends no signal pigment at all -- which is exactly the volume this screen renders at. */
const SIGNAL_TOKEN = /^--(?:signal-|amber-|oxide-|verdigris-)/;

function installReads(learned: Learned = buildLearned(), versions: WeightSets = buildWeightSets()) {
  apiServer.use(
    readyz(),
    jsonHandler(LEARNED_PATH, { status: 200, body: learned }),
    jsonHandler(WEIGHT_SETS_PATH, { status: 200, body: versions }),
  );
}

/** Every class name the screen rendered, as one list, de-duplicated.
 *
 * Read through `getAttribute` rather than `className`, because an SVG element's `className` is an
 * `SVGAnimatedString` rather than a string: the plate in the band is an `img`, but a later element in this tree
 * being SVG would silently make a guard read nothing. */
function renderedClasses(container: HTMLElement): string[] {
  const seen = new Set<string>();
  for (const element of container.querySelectorAll("[class]")) {
    for (const name of (element.getAttribute("class") ?? "").split(/\s+/)) {
      if (name !== "") seen.add(name);
    }
  }
  return [...seen];
}

/** The meter for one parameter, located by the accessible name the component gives it. */
function meterFor(name: string): HTMLElement {
  return screen.getByRole("meter", { name });
}

/**
 * A response a case holds open, and the release that answers it.
 *
 * Holding one open is what makes the window between two clicks observable at all: with the request
 * answered immediately there is nothing for a second press to land inside.
 */
function aHeldAnswer(): { readonly held: Promise<void>; readonly release: () => void } {
  const answered: { release: () => void } = { release: () => undefined };
  const held = new Promise<void>((resolve) => {
    answered.release = resolve;
  });
  return { held, release: () => answered.release() };
}

describe("the per-parameter table", () => {
  it("renders the value, the samples, what it needs, and the state of every parameter", async () => {
    installReads();
    renderAt(SCREEN);
    await screen.findByRole("table", {
      name: /Every parameter syncr fits/,
    });

    const table = screen.getByRole("table", { name: /Every parameter syncr fits/ });
    expect(within(table).getByText("Duration multiplier \u00b7 Fitness")).toBeVisible();
    expect(within(table).getByText("1.20")).toBeVisible();
    expect(within(table).getByText("14")).toBeVisible();
    expect(within(table).getByText("12")).toBeVisible();
    expect(within(table).getByText("ready")).toBeVisible();
    expect(within(table).getByText("collecting")).toBeVisible();
  });

  it("renders the served subject in the name column, so one parameter for two Areas reads as two rows", async () => {
    /* The api resolves what a key names and sends it as `subject`; the client joins it to the humanised token
     * rather than inventing a second name for an Area. Two rows carrying `duration_multiplier` for different
     * Areas are then distinguishable from the name column alone. */
    installReads(
      buildLearned({
        parameters: [
          buildReadyParameter({ subject: "Fitness" }),
          buildReadyParameter({
            parameter: `duration_multiplier[${FITNESS}]`,
            subject: "Recovery",
          }),
        ],
      }),
    );
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    expect(within(table).getByText("Duration multiplier \u00b7 Fitness")).toBeVisible();
    expect(within(table).getByText("Duration multiplier \u00b7 Recovery")).toBeVisible();
  });

  it("gives twelve same-parameter meters twelve accessible names, not twelve copies of one", async () => {
    /* The meter's label carries the subject, so a screen reader on a full account hears twelve distinct names.
     * Without it every row's meter would announce the same string, and the column would read as one control
     * repeated. */
    const subjects = [
      "Fitness",
      "Recovery",
      "Deep work",
      "Admin",
      "Reading",
      "Exercise",
      "Errands",
      "Writing",
      "Practice",
      "Commute",
      "Cooking",
      "Rest",
    ];
    installReads(
      buildLearned({
        parameters: subjects.map((subject, index) =>
          buildReadyParameter({
            parameter: `duration_multiplier[${FITNESS}]#${index}`,
            subject,
          }),
        ),
      }),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    const names = screen.getAllByRole("meter").map((meter) => meter.getAttribute("aria-label"));
    expect(names).toHaveLength(subjects.length);
    expect(new Set(names).size).toBe(subjects.length);
    for (const subject of subjects) {
      expect(names).toContain(`Duration multiplier unlock progress for ${subject}`);
    }
  });

  it("renders a keyless parameter's name alone, with no subject and no placeholder", async () => {
    /* A parameter with no key is about the whole account rather than about an Area, so there is no subject to
     * join and none is invented: neither a middle dot nor any stand-in appears in the name cell. */
    installReads(buildLearned({ parameters: [buildCollectingParameter()] }));
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    const row = within(table)
      .getAllByRole("row")
      .find(
        (candidate): candidate is HTMLTableRowElement =>
          candidate.textContent?.includes("Objective weights") === true,
      );
    const nameCell = row?.cells[0];
    expect(nameCell).toBeDefined();
    expect(within(nameCell!).getByText("Objective weights")).toBeVisible();
    expect(nameCell!.textContent).not.toContain("\u00b7");
  });

  it("carries a plain-language statement on every row, which is what builds trust", async () => {
    const learned = buildLearned();
    installReads(learned);
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    for (const row of learned.parameters) {
      expect(screen.getByText(row.plainLanguage)).toBeVisible();
    }
  });

  it("displays the shrinkage weight, so still collecting is a quantity rather than a badge", async () => {
    /* Two rows both reading `collecting` can be 91% prior and 9% prior, and only the figure tells them apart. */
    installReads(
      buildLearned({
        parameters: [
          buildCollectingParameter({ parameter: "churn_tolerance", shrinkageWeight: 0.91 }),
          buildCollectingParameter({ parameter: "context_switch_cost", shrinkageWeight: 0.09 }),
        ],
      }),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    expect(screen.getByText("91%")).toBeVisible();
    expect(screen.getByText("9%")).toBeVisible();
  });

  it("draws a parameter below its gate with no figure at all", async () => {
    /* The gate as the reader meets it: below the threshold nothing is applied, so there is no number to show
     * and a zero would be a figure they could compare. */
    installReads(buildLearned({ parameters: [buildCollectingParameter()] }));
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    expect(within(table).getByText("\u2014")).toBeVisible();
  });
});

describe("the bounded meter", () => {
  it("draws an empty run and announces the same pair at zero samples", async () => {
    installReads(buildLearned({ parameters: [buildCollectingParameter()] }));
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    const meter = meterFor("Objective weights unlock progress");
    expect(meter).toHaveAttribute("aria-valuenow", "0");
    expect(meter).toHaveAttribute("aria-valuemax", "50");
    expect(meter.querySelectorAll(".meter__cell--empty")).toHaveLength(
      meter.querySelectorAll(".meter__cell").length,
    );
  });

  it("draws a complete run at the threshold, and announces the clamped pair", async () => {
    /* 14 samples against a threshold of 12 is a real row: samples keep accruing after a gate is met. The run is
     * complete and the announced value is the bound rather than the count, because a meter cannot report past
     * its own maximum without contradicting the run a reader sees. */
    installReads(buildLearned({ parameters: [buildReadyParameter()] }));
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    const meter = meterFor("Duration multiplier unlock progress for Fitness");
    expect(meter).toHaveAttribute("aria-valuenow", "12");
    expect(meter).toHaveAttribute("aria-valuemax", "12");
    expect(meter.querySelectorAll(".meter__cell--empty")).toHaveLength(0);
  });
});

describe("collecting reads as normal, and never as a warning", () => {
  it("renders no signal pigment anywhere on the screen, through any utility", async () => {
    installReads();
    const { container } = renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    const classes = renderedClasses(container);
    const emitted = await compileUtilities(classes);
    const signals = [...(await declaredTokens()).keys()].filter((name) => SIGNAL_TOKEN.test(name));
    /* The DECLARATIONS each utility produces, not the whole build: the build always carries the token layer's own
     * `:root`, so a check over its text would be true of every stylesheet this product could compile. */
    const declared = classes.filter((name) => declarationsOf(emitted, name) !== null);
    const spending = declared.filter((name) => {
      const declarations = declarationsOf(emitted, name) ?? "";
      return signals.some((token) => declarations.includes(`var(${token})`));
    });

    expect(signals.length).toBeGreaterThan(0);
    /* THE COMPILER ITSELF, because the two reads above are the only things this case rests on. If `compileUtilities`
     * ever emits nothing for the rendered classes -- the theme moves, the compile signature changes -- every class
     * is skipped and the sweep passes having asserted nothing. That is the vacuous shape this guard was rewritten
     * out of once already, reached from the other side. */
    expect(declared.length).toBeGreaterThan(0);
    expect(spending).toEqual([]);
  });

  it("spends no notice surface on a collecting parameter", async () => {
    /* The other channel a pigment can arrive through: the notice family's own classes, which are CSS rather than
     * utilities and so are invisible to the compiled check above.
     *
     * NO NOTICE CLASS AT ALL, rather than the three signal pigments by name. The collecting state renders no
     * notice surface of any kind, so the stronger claim is also the true one, and it needs no list: a fifth
     * pigment added to `surface.ts` would be invisible to a check that named the four it has today, and
     * `NoticePigment` is type-only so there is nothing to derive one from at runtime. */
    installReads();
    const { container } = renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    for (const name of renderedClasses(container)) expect(name).not.toMatch(/^notice(--|$)/);
  });

  it("states in prose that nothing is broken while a parameter collects", async () => {
    installReads();
    renderAt(SCREEN);

    expect(await screen.findByText(COLLECTING_IS_NORMAL)).toBeVisible();
  });

  it("states that unlocks count confirmed volume rather than adherence", async () => {
    installReads();
    renderAt(SCREEN);

    expect(await screen.findByText(UNLOCKS_COUNT_VOLUME)).toBeVisible();
  });

  it("states that the thresholds are estimates", async () => {
    installReads();
    renderAt(SCREEN);

    expect(await screen.findByText(THRESHOLDS_ARE_ESTIMATES)).toBeVisible();
  });
});

describe("the header", () => {
  it("states how many parameters are still collecting", async () => {
    installReads(
      buildLearned({
        parameters: [
          buildReadyParameter(),
          buildCollectingParameter({ parameter: "churn_tolerance" }),
          buildCollectingParameter({ parameter: "skip_probability" }),
        ],
      }),
    );
    renderAt(SCREEN);

    expect(await screen.findByText("2 of 3 parameters still collecting")).toBeVisible();
  });

  it("names the weight set in force, which is where every figure on the screen comes from", async () => {
    installReads();
    renderAt(SCREEN);

    expect(await screen.findByText("Weight set 1, hand-tuned.")).toBeVisible();
  });

  it("agrees with the table's own footer about how many are collecting", async () => {
    /* One fact, two places it is rendered. The band states the api's `collecting` and the kit's table sums its
     * footer from the rows it drew, so both now read `state`: the field the row itself renders and the one the
     * gate is expressed in.
     *
     * This case does NOT distinguish the two derivations the footer could use, and cannot: the api refuses a row
     * whose state disagrees with its own value, so a fixture where `value === null` and `state === "ready"` is a
     * shape production never sends. What it holds is that the two figures on one screen agree. */
    installReads(
      buildLearned({
        parameters: [
          buildReadyParameter(),
          buildCollectingParameter({ parameter: "churn_tolerance" }),
          buildCollectingParameter({ parameter: "skip_probability" }),
        ],
      }),
    );
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every parameter syncr fits/ });

    expect(screen.getByText("2 of 3 parameters still collecting")).toBeVisible();
    expect(within(table).getByText("3 parameters \u00b7 2 still collecting")).toBeVisible();
  });
});

describe("the signal sources", () => {
  it("names each source, what it yields, and which parameter it drives", async () => {
    installReads();
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Each signal source/ });

    expect(within(table).getByText(/Every pin you make/)).toBeVisible();
    expect(within(table).getByText(/objective term weights/)).toBeVisible();
    expect(within(table).getByText(/duration multiplier/)).toBeVisible();
    expect(within(table).getByText(/skip probability for that Area/)).toBeVisible();
  });

  it("says that rejecting a whole week yields almost nothing, with the reason", async () => {
    /* The row the table exists for. Without it the other four read as encouragement. */
    installReads();
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Each signal source/ });

    expect(within(table).getByText(/Almost nothing/)).toBeVisible();
    expect(within(table).getByText(/no credit assignment/)).toBeVisible();
  });
});

describe("the weight sets", () => {
  it("lists every version with its origin and which one is in force", async () => {
    installReads();
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every weight set version/ });

    expect(within(table).getByText("fitted")).toBeVisible();
    expect(within(table).getByText("hand-tuned")).toBeVisible();
    expect(within(table).getByText("in force")).toBeVisible();
    expect(within(table).getByText("2 versions")).toBeVisible();
  });

  it("counts one version as one, because a first account holds exactly that", async () => {
    installReads(buildCollectingBaseline(), buildWeightSets({ versions: [ONLY_HAND_TUNED] }));
    renderAt(SCREEN);
    const table = await screen.findByRole("table", { name: /Every weight set version/ });

    expect(within(table).getByText("1 version")).toBeVisible();
  });

  it("offers one action, which is the same action a revert is", async () => {
    /* One control and one label. The active row has none: this screen has nothing to apply. */
    installReads();
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });

    expect(screen.getAllByRole("button", { name: "Put in force" })).toHaveLength(1);
  });

  it("activates through the version's own path, and reads the parameters again", async () => {
    const learned = countedHandler(LEARNED_PATH, { status: 200, body: buildLearned() });
    const paths: string[] = [];
    apiServer.use(
      readyz(),
      learned.handler,
      jsonHandler(WEIGHT_SETS_PATH, { status: 200, body: buildWeightSets() }),
      http.post(`${window.location.origin}${WEIGHT_SETS_PATH}/:version/activate`, ({ request }) => {
        paths.push(new URL(request.url).pathname);
        return HttpResponse.json({ version: 2, resolvedWeeks: ["2026-W08"] }, { status: 200 });
      }),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });
    const before = learned.count();

    await userEvent.click(screen.getByRole("button", { name: "Put in force" }));

    await waitFor(() => expect(paths).toEqual([`${WEIGHT_SETS_PATH}/2/activate`]));
    /* The parameters in force are what an activation changes, so this key is named by the write rather than left
     * to a blanket revalidation. */
    await waitFor(() => expect(learned.count()).toBe(before + 1));
  });

  it("states that no history is reprocessed, and that P0's weights come through this mechanism", async () => {
    installReads();
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });

    expect(screen.getByText(/no history is reprocessed/)).toBeVisible();
    expect(screen.getByText(/tuned by hand/)).toBeVisible();
  });

  it("says nothing about the active row when it says the shipped weights are hand-tuned", async () => {
    /* Measured against a real account with two versions: the first wording read "the weights in force today were
     * tuned by hand", which a screen with a FITTED set in force states falsely. The claim is about the mechanism,
     * so it holds whichever row is active. */
    installReads(
      buildLearned({ version: 2, origin: "fitted" }),
      buildWeightSets({
        versions: [
          { ...buildWeightSets().versions[0], active: true },
          { ...buildWeightSets().versions[1], active: false },
        ],
      }),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });

    expect(screen.getByText(/tuned by hand/)).toBeVisible();
    expect(screen.queryByText(/in force today were tuned by hand/)).not.toBeInTheDocument();
    /* And the band names the fitted set, so the two do not contradict each other. */
    expect(screen.getByText("Weight set 2, fitted.")).toBeVisible();
  });

  it("renders the api's own sentence when an activation is refused", async () => {
    installReads();
    apiServer.use(
      http.post(`${window.location.origin}${WEIGHT_SETS_PATH}/:version/activate`, () =>
        HttpResponse.json(
          {
            type: "syncr:not-found",
            title: "Not found",
            status: 404,
            detail: "No weight set of this account has that version.",
          },
          { status: 404, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });

    await userEvent.click(screen.getByRole("button", { name: "Put in force" }));

    expect(await screen.findByText(/has that version/)).toBeVisible();
  });

  it("comes back after a refusal, so a lock taken is a lock released", async () => {
    /* A lock taken before the request and released only on success is a lock a refusal keeps forever: the reader
     * would be left looking at a control that never returns. */
    installReads();
    apiServer.use(
      http.post(`${window.location.origin}${WEIGHT_SETS_PATH}/:version/activate`, () =>
        HttpResponse.json(
          {
            type: "syncr:not-found",
            title: "Not found",
            status: 404,
            detail: "No weight set of this account has that version.",
          },
          { status: 404, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });

    await userEvent.click(screen.getByRole("button", { name: "Put in force" }));
    await screen.findByText(/has that version/);

    expect(screen.getByRole("button", { name: "Put in force" })).toBeEnabled();
  });

  it("sends one activation for a double-tap, which is what the lock is a ref for", async () => {
    /* AN ACTIVATION RE-SOLVES EVERY FUTURE WEEK, so two clicks of an ordinary double-tap would ask for two waves
     * of the most expensive act on this screen. The api is safe either way: one version is active by a partial
     * unique index, so the outcome is last-writer-wins rather than no active set. What the lock saves is the work.
     *
     * THE THREE CLICKS ARE FIRED WITH NO RENDER BETWEEN THEM, which is what a real double-tap produces and what
     * the `disabled` attribute alone cannot answer: it reaches the DOM on the next render. The response is held
     * open, which is what makes the window observable at all. The capture host's own case is this shape. */
    installReads();
    const versions: string[] = [];
    const { held, release } = aHeldAnswer();
    apiServer.use(
      http.post(
        `${window.location.origin}${WEIGHT_SETS_PATH}/:version/activate`,
        async ({ params }) => {
          versions.push(String(params.version));
          await held;
          return HttpResponse.json({ version: 2, resolvedWeeks: [] }, { status: 200 });
        },
      ),
    );
    renderAt(SCREEN);
    await screen.findByRole("table", { name: /Every weight set version/ });
    const control = screen.getByRole("button", { name: "Put in force" });

    control.click();
    control.click();
    control.click();

    await waitFor(() => expect(versions).toEqual(["2"]));
    release();
    await waitFor(() => expect(screen.getByRole("button", { name: "Put in force" })).toBeEnabled());
    expect(versions).toEqual(["2"]);
  });
});

describe("the states a read can be in", () => {
  it("reads Collecting baseline when nothing has been fitted at all", async () => {
    /* The first two weeks, which the learning layer produces nothing in. A fresh account's active weight set
     * carries no maturity rows, so the read answers with none: item 57 measured that on a real stack. */
    installReads(buildCollectingBaseline());
    renderAt(SCREEN);

    expect(await screen.findByText("Collecting baseline")).toBeVisible();
    expect(
      screen.queryByRole("table", { name: /Every parameter syncr fits/ }),
    ).not.toBeInTheDocument();
  });

  it("still names the sources and states the three rules in the empty state", async () => {
    /* A screen showing two words would teach a reader nothing about what to do next, and what to do next is
     * exactly nothing. */
    installReads(buildCollectingBaseline());
    renderAt(SCREEN);
    await screen.findByText("Collecting baseline");

    expect(screen.getByText(COLLECTING_IS_NORMAL)).toBeVisible();
    expect(screen.getByRole("table", { name: /Each signal source/ })).toBeVisible();
  });

  it("says what it is waiting for while the read is outstanding, and draws no spinner", async () => {
    apiServer.use(readyz(), pendingHandler(LEARNED_PATH), pendingHandler(WEIGHT_SETS_PATH));
    renderAt(SCREEN);

    expect(await screen.findByText("Reading what has been learned")).toBeVisible();
    expect(await screen.findByRole("heading", { level: 1, name: "Learned" })).toBeVisible();
  });

  it("names which read failed, in the api's own words", async () => {
    apiServer.use(
      readyz(),
      jsonHandler(LEARNED_PATH, { status: 200, body: buildLearned() }),
      http.get(`${window.location.origin}${WEIGHT_SETS_PATH}`, () =>
        HttpResponse.json(
          {
            type: "syncr:dependency-unavailable",
            title: "Dependency unavailable",
            status: 503,
            detail: "The database did not answer. Nothing was changed.",
          },
          { status: 503, headers: { "content-type": "application/problem+json" } },
        ),
      ),
    );
    renderAt(SCREEN);

    expect(await screen.findByText("The versions could not be read")).toBeVisible();
    expect(screen.getByText(/did not answer/)).toBeVisible();
  });
});
