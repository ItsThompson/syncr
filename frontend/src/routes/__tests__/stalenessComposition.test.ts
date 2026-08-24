/* THE PROOF THAT NO CLIENT SURFACE COMPUTES STALENESS FOR ITSELF.
 *
 * Whether a feed is stale, how long it has been failing, and which days its outage puts in doubt are decided
 * once, on the api, where the anchors live. The surfaces render the notice that read produces; the proof has
 * two halves:
 *
 *   THE SCAN. No production file under this tree names a staleness threshold or a staleness predicate, so a
 *   second computation cannot be reintroduced silently -- not as a copy of the deleted one, not under a new
 *   name spelled the same way.
 *
 *   THE FIGURE. Both surfaces are rendered against a notice naming a threshold figure NO client file states,
 *   beside a source row whose sync state looks healthy. The sentence reaches the reader anyway: what moves
 *   the figure is an edit on the server, and nothing here.
 *
 * The composer's own suite (`packages/syncr-api/tests/test_feed_notices.py`) owns the threshold's behaviour;
 * the integration suite owns its arrival on the wire. This file owns the client side of the seam. */

import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { appSourceDir } from "../../../scripts/lib/paths.ts";
import { apiServer } from "../../testing/apiServer";
import { jsonHandler } from "../../testing/apiStub";
import { renderAt } from "../../testing/renderRoute";
import { SOURCE_TIMETABLE, buildSource } from "../settings/__tests__/fixtures";
import { settingsHandlers } from "../settings/__tests__/handlers";
import { buildAreas, buildDay } from "../today/__tests__/fixtures";
import { hostSpan, hostToday, stubDay } from "../today/__tests__/render";

/* The identifiers a staleness computation needs. Spelled in parts so this file's own text cannot match them:
 * a guard that fails on itself guards nothing. */
const PATTERN_PARTS = ["isFeed", "Stale", "STALE", "_AFTER"];
const THRESHOLD_PATTERN = new RegExp(
  `${PATTERN_PARTS[0]}${PATTERN_PARTS[1]}|${PATTERN_PARTS[2]}${PATTERN_PARTS[3]}`,
);

/** The surfaces that render the api's notice. A staleness computation here is a second opinion on one fact. */
const SURFACE_DIRS = new Set(["routes/today"]);
const SURFACE_FILES = new Set(["routes/settings/sourceNotices.ts"]);

/** Every production source file under the app, as [relative path, text]. Tests are not production. */
async function productionSources(root: string): Promise<[string, string][]> {
  const entries = await readdir(root, { withFileTypes: true, recursive: true });

  return Promise.all(
    entries
      .map((entry) => path.join(entry.parentPath, entry.name))
      .filter((full) => {
        if (!/\.(ts|tsx)$/.test(full) || /\.test\./.test(full)) return false;
        return !full.split(path.sep).includes("__tests__");
      })
      .map(async (full): Promise<[string, string]> => {
        const file = path.relative(root, full).split(path.sep).join("/");
        return [file, await readFile(full, "utf8")];
      }),
  );
}

describe("no client surface computes staleness for itself", () => {
  it("names no staleness threshold or predicate anywhere in production source", async () => {
    const sources = await productionSources(appSourceDir);
    expect(sources.length).toBeGreaterThan(0);

    const offenders = sources
      .filter(([, text]) => THRESHOLD_PATTERN.test(text))
      .map(([file]) => file);

    expect(offenders).toEqual([]);
  });

  /* THE POSITIVE CONTROL. Without it the pattern above could be unmatchable -- too narrow, or anchored wrong --
   * and every surface would pass while computing whatever it liked. */
  it("reports a surface that recomputes staleness, which is what the scan exists to refuse", async () => {
    const planted = [
      "export function isFeed".concat("Stale(source: unknown): boolean { return true; }"),
    ].join("\n");

    expect(THRESHOLD_PATTERN.test(planted)).toBe(true);
  });

  /* The notice can only come from scope.dates and the response's own list, so any reading of the failure
   * fields on either surface is a threshold comparison waiting to be written. (The rejection panel's `since`
   * reads the last success to state an instant; it decides nothing from it.) */
  it("reads no failure state on either surface, where only the api's notices are read", async () => {
    const sources = await productionSources(appSourceDir);
    const surfaces = sources.filter(
      ([file]) =>
        SURFACE_DIRS.has(file.split("/").slice(0, 2).join("/")) || SURFACE_FILES.has(file),
    );

    expect(surfaces.length).toBeGreaterThan(1);
    expect(
      surfaces.filter(([, text]) => /lastError|is_feed_stale/.test(text)).map(([file]) => file),
    ).toEqual([]);
  });
});

describe("changing the server figure moves both surfaces with no client edit", () => {
  /* Ninety hours is stated by NO client file; the client constant this ticket deleted said twelve. If these
   * sentences reach a reader, the figure came across the wire, and moving it is an api change alone. */
  const NINETY_HOUR_SENTENCE = "more than 90 hours";

  const feedNotice = (dates: string[] = []) => [
    {
      id: `calendar.feed-stale.${SOURCE_TIMETABLE}`,
      volume: "panel",
      pigment: "amber",
      title: "Timetable could not be read",
      detail: `The feed did not answer. It last answered 4 days ago. A feed is reported once it has been failing for ${NINETY_HOUR_SENTENCE}.`,
      unavailable: ["Reading new commitments from Timetable"],
      stillWorks: [
        "The commitments this feed already contributed, which are retained and marked possibly stale",
        "Solving the week, which still plans around every commitment already read",
      ],
      since: new Date().toISOString(),
      action: null,
      scope: { screen: "settings", sourceId: SOURCE_TIMETABLE, dates },
    },
  ];

  /* THE ROW LOOKS HEALTHY. lastError is null and the last success is minutes old, so a surface computing
   * staleness for itself would render nothing at any threshold. */
  const freshlySynced = buildSource();

  function sourcesRead(notices: ReturnType<typeof feedNotice>) {
    return jsonHandler("/api/v1/calendar-sources", {
      status: 200,
      body: { sources: [freshlySynced], notices },
    });
  }

  it("Settings renders the api's ninety-hour sentence over a fresh-looking row", async () => {
    /* The specific read is installed ahead of the shared set, because msw's first matching handler wins. */
    apiServer.use(sourcesRead(feedNotice()), ...settingsHandlers());
    renderAt("/settings");

    await waitFor(() =>
      expect(screen.getByRole("status", { name: "Timetable could not be read" })).toHaveTextContent(
        NINETY_HOUR_SENTENCE,
      ),
    );
  });

  it("Today renders the same sentence on the day the api named, over the same row", async () => {
    stubDay(
      buildDay({
        date: hostToday(),
        span: hostSpan(),
        behind: [],
        ahead: [
          {
            blockId: "b1".repeat(32),
            interval: {
              start: `${hostToday()}T09:00:00+00:00`,
              end: `${hostToday()}T10:00:00+00:00`,
            },
            durationMinutes: 60,
            areaId: null,
            areaName: null,
            title: "Lecture",
            origin: "anchor",
            outcome: null,
          },
        ],
        blockCount: 1,
        presumedCount: 0,
      }),
      buildAreas(),
    );
    apiServer.use(sourcesRead(feedNotice([hostToday()])));
    renderAt("/today");

    const notice = await waitFor(() => {
      const found = [...document.querySelectorAll(".notice--amber")];
      expect(found).toHaveLength(1);
      return found[0];
    });

    expect(notice.textContent).toContain(NINETY_HOUR_SENTENCE);
  });
});
