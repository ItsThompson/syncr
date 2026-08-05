/* WHERE A HEADLESS BROWSER IS, AND HOW ONE PAGE BECOMES ONE SCREENSHOT.
 *
 * THE ONLY GATE IN THIS FRONTEND THAT LOOKS AT A RENDERED PIXEL. Every other check reads a declaration, a class
 * list, an attribute or the built artifact, and each of those is blind to a COMPOSED result: three real defects on
 * the week grid were compositions, and each was found by a person opening a browser once. A `-webkit-line-clamp`
 * shorthand supplied an end-ellipsis that no reading of `white-space` or `text-overflow` could see; a `border`
 * shorthand collapsed a block's three edges into four; a proposal target lost the Area's top rule to the same
 * shorthand. This is the input those three share.
 *
 * NO BROWSER IS DECLARED AS A DEPENDENCY, so the one already installed is used and its absence is REPORTED rather
 * than skipped. A check that passes when it cannot look is worse than no check: it reports a claim it never tested,
 * which is the suppression shape this repository has been bitten by twice. */

import { access, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { spawn } from "node:child_process";
import { tmpdir } from "node:os";
import path from "node:path";

/** Where a headless Chromium lives on the platforms this is run on. Ordered by which one a developer has. */
const CANDIDATES = [
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Chromium.app/Contents/MacOS/Chromium",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
];

/** The environment variable an operator points at a browser this list does not know. */
export const BROWSER_ENV = "SYNCR_CHROME";

export async function findBrowser(): Promise<string | null> {
  const named = process.env[BROWSER_ENV];
  const paths = named === undefined || named === "" ? CANDIDATES : [named, ...CANDIDATES];
  for (const candidate of paths) {
    try {
      await access(candidate);
      return candidate;
    } catch {
      continue;
    }
  }
  return null;
}

export interface ShotRequest {
  readonly browser: string;
  readonly html: string;
  /** Files written beside the page, by name, so it can link the built stylesheet relatively. */
  readonly beside?: Readonly<Record<string, string>> | undefined;
  readonly widthPx: number;
  readonly heightPx: number;
}

/** One page, rendered, as the PNG bytes AND whatever the page reported about itself. */
export interface Shot {
  readonly png: Buffer;
  /** The text of the page's own `<pre id="readings">`, or an empty string where it wrote none. */
  readonly readings: string;
}

/**
 * One page, rendered and screenshotted, with its own readings alongside.
 *
 * TWO PASSES, BECAUSE A SCREENSHOT AND A GEOMETRY READING ARE TWO QUESTIONS. Pixels answer what a reader sees; the
 * page's own `getBoundingClientRect` answers where a box is, which a screenshot cannot say and which is the figure the
 * button-centring defect was measured in. Chromium writes one or the other per invocation, so it is invoked twice over
 * the same directory.
 *
 * `--force-device-scale-factor=1` so a pixel in the answer is a CSS pixel wherever this runs, and `--hide-scrollbars`
 * so a scrollbar cannot shift the geometry being measured. The virtual time budget is what makes the shot
 * deterministic: it is taken after the page has settled rather than after a wall-clock guess.
 */
export async function screenshot(request: ShotRequest): Promise<Shot> {
  const directory = await mkdtemp(path.join(tmpdir(), "syncr-render-"));
  const page = path.join(directory, "probe.html");
  const shot = path.join(directory, "probe.png");
  for (const [name, content] of Object.entries(request.beside ?? {})) {
    const target = path.join(directory, name);
    /* A built asset's name carries its own directory, `assets/index-<hash>.css`, so the page's neighbour has to be
     * created at that path rather than at the temporary root. */
    await mkdir(path.dirname(target), { recursive: true });
    await writeFile(target, content, "utf8");
  }
  await writeFile(page, request.html, "utf8");

  const common = [
    "--headless=new",
    "--disable-gpu",
    "--allow-file-access-from-files",
    "--hide-scrollbars",
    "--force-device-scale-factor=1",
    `--window-size=${String(request.widthPx)},${String(request.heightPx)}`,
    "--virtual-time-budget=3000",
  ];

  await run(request.browser, [...common, `--screenshot=${shot}`, `file://${page}`]);
  const dom = await capture(request.browser, [...common, "--dump-dom", `file://${page}`]);

  return { png: await readFile(shot), readings: readingsIn(dom) };
}

/** The text the page put in its own `<pre id="readings">`, unescaped. */
function readingsIn(dom: string): string {
  const found = /<pre id="readings">([\s\S]*?)<\/pre>/.exec(dom);
  if (found === null) return "";
  return found[1]
    .replaceAll("&quot;", '"')
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function run(command: string, args: readonly string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...args], { stdio: "ignore" });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${path.basename(command)} exited ${String(code)}`));
    });
  });
}

function capture(command: string, args: readonly string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...args], { stdio: ["ignore", "pipe", "ignore"] });
    let out = "";
    child.stdout.on("data", (chunk: Buffer) => {
      out += chunk.toString();
    });
    child.on("error", reject);
    child.on("exit", () => {
      resolve(out);
    });
  });
}
