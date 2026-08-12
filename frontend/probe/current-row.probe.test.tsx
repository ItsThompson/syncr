/* WHAT A BROWSER GIVES A CURRENT LEDGER ROW, over the built stylesheet.
 *
 * NOT A GATE, AND NOT IN THE SUITE, for the reason the table's probe is not: the committed suite matches the rules
 * against the element with postcss and resolves them in document order, which is a model of the cascade rather
 * than the cascade. This settles the one question that model cannot: whether the ledger row's own borders and the
 * kit's state rule compose the way the two files' declarations say they do. It is run explicitly:
 *
 *   npx vite build
 *   npx vitest run --config probe/vitest.config.ts
 *
 * WHAT IT SETTLES. The current row takes a fill and a coloured left rule the resting row does not; the rule is 3px
 * in both, so becoming current moves no label and changes no height; and the ledger's own hairline is untouched by
 * either. The first is the state; the last two are the reasons `states.css` gives for drawing the rule transparent
 * at rest rather than adding a width.
 *
 * The markup is the component's own, rendered with `renderToStaticMarkup`, so the page cannot drift from the
 * product. The sheet is the built bundle rather than the two source files, because the reset and the token layer
 * only reach an element through the bundle, and a probe linking `states.css` alone would measure neither.
 *
 * Nothing is written inside the repository: the page, the stylesheet and the profile go to a fresh temporary
 * directory whose path is printed with the stylesheet's digest, so a reading can be traced to one exact artifact. */

import { createHash } from "node:crypto";
import { mkdtemp, readdir, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";

import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";

import { BROWSER_ENV, findBrowser } from "../scripts/check-render/browser.ts";
import { LedgerRow } from "../src/ui/domain/ledger/LedgerRow";

interface Reading {
  readonly name: string;
  readonly backgroundColor: string;
  readonly borderLeftColor: string;
  readonly borderLeftWidth: string;
  readonly borderBottomWidth: string;
  readonly heightPx: number;
  readonly titleLeftPx: number;
}

const CASES = [
  { name: "current", isCurrent: true },
  { name: "resting", isCurrent: false },
] as const;

function markup({ name, isCurrent }: (typeof CASES)[number]): string {
  const row = renderToStaticMarkup(
    <LedgerRow
      timeRange="09:00-09:30"
      duration="30m"
      title="Standup"
      area={{ name: "Career", pigment: "01" }}
      isCurrent={isCurrent}
    />,
  );
  return `<div class="case" data-case="${name}" style="width: 600px">${row}</div>`;
}

const PAGE_SCRIPT = `
  const readings = [...document.querySelectorAll(".case")].map((box) => {
    const row = box.firstElementChild;
    const style = getComputedStyle(row);
    const title = box.querySelector(".ledger__title");
    return {
      name: box.dataset.case,
      backgroundColor: style.backgroundColor,
      borderLeftColor: style.borderLeftColor,
      borderLeftWidth: style.borderLeftWidth,
      borderBottomWidth: style.borderBottomWidth,
      heightPx: Math.round(row.getBoundingClientRect().height * 100) / 100,
      titleLeftPx: Math.round(title.getBoundingClientRect().left * 100) / 100,
    };
  });
  document.getElementById("readings").textContent = JSON.stringify(readings);
`;

async function bundleCss(): Promise<string> {
  const assets = path.resolve(import.meta.dirname, "..", "dist", "assets");
  const names = await readdir(assets);
  const sheet = names.find((name) => name.endsWith(".css"));
  if (sheet === undefined)
    throw new Error(`no built stylesheet in ${assets}: run \`npx vite build\``);
  return readFile(path.join(assets, sheet), "utf8");
}

/* Resolves on the completed dump rather than on the process exiting, because Chrome holds an uninitialised
 * profile directory open indefinitely after it has written the document. */
function dumpDom(browser: string, run: string, page: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(
      browser,
      [
        "--headless=new",
        `--user-data-dir=${path.join(run, "chrome-profile")}`,
        "--disable-gpu",
        "--allow-file-access-from-files",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=1440,900",
        "--virtual-time-budget=3000",
        "--dump-dom",
        `file://${page}`,
      ],
      { stdio: ["ignore", "pipe", "ignore"] },
    );
    let out = "";
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
      if (out.includes("</html>")) {
        child.kill();
        resolve(out);
      }
    });
    child.on("error", reject);
    child.on("exit", () => {
      resolve(out);
    });
  });
}

async function measure(): Promise<Reading[]> {
  const browser = await findBrowser();
  if (browser === null) throw new Error(`no Chrome found. Point ${BROWSER_ENV} at one`);

  const page = [
    "<!doctype html>",
    '<html lang="en"><head><meta charset="utf-8">',
    '<link rel="stylesheet" href="bundle.css"></head><body>',
    ...CASES.map(markup),
    '<pre id="readings"></pre>',
    `<script>${PAGE_SCRIPT}</script>`,
    "</body></html>",
  ].join("\n");

  const run = await mkdtemp(path.join(tmpdir(), "syncr-current-probe-"));
  const css = await bundleCss();
  process.stdout.write(
    `measured over ${String(Buffer.byteLength(css))} bytes of built css, sha256 ${createHash(
      "sha256",
    )
      .update(css)
      .digest("hex")
      .slice(0, 16)}\n`,
  );
  process.stdout.write(`the page and the stylesheet are in ${run}\n`);
  await writeFile(path.join(run, "bundle.css"), css, "utf8");
  await writeFile(path.join(run, "page.html"), page, "utf8");

  const dom = await dumpDom(browser, run, path.join(run, "page.html"));
  const found = /<pre id="readings">([\s\S]*?)<\/pre>/.exec(dom);
  if (found === null) throw new Error("the page reported no readings");
  return JSON.parse(found[1].replaceAll("&quot;", '"').replaceAll("&amp;", "&")) as Reading[];
}

describe("a current ledger row in a browser", () => {
  let readings: readonly Reading[] = [];

  beforeAll(async () => {
    readings = await measure();
    process.stdout.write(`${JSON.stringify(readings, null, 2)}\n`);
  });

  const by = (name: string): Reading => {
    const found = readings.find((reading) => reading.name === name);
    if (found === undefined) throw new Error(`no reading for ${name}`);
    return found;
  };

  it("takes a fill the resting row does not", () => {
    expect(by("current").backgroundColor).not.toBe(by("resting").backgroundColor);
  });

  it("takes a 3px left rule that the resting row reserves transparent", () => {
    expect(by("current").borderLeftWidth).toBe("3px");
    expect(by("resting").borderLeftWidth).toBe("3px");
    expect(by("current").borderLeftColor).not.toBe(by("resting").borderLeftColor);
  });

  it("moves no label and changes no height, because the rule is reserved at rest", () => {
    expect(by("current").titleLeftPx).toBe(by("resting").titleLeftPx);
    expect(by("current").heightPx).toBe(by("resting").heightPx);
  });

  it("keeps the ledger's own hairline, which the state rule does not touch", () => {
    expect(by("current").borderBottomWidth).toBe(by("resting").borderBottomWidth);
  });
});
