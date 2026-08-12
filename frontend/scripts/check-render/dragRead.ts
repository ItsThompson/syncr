/* THE SHIPPED POINTER READ, COMPILED FOR THE PROBE PAGE.
 *
 * The page needs the function the product uses, not a copy of it: a copy would answer correctly with the horizontal
 * comparison deleted from `useDiscreteDrag.ts`, which is the defect the reading exists to catch. Nothing else in this
 * gate can reach that module. The runtime a script runs under resolves neither an extensionless relative import nor a
 * directory, and `useDiscreteDrag.ts` reaches the snap through the kit's barrel, so `node` answers
 * `ERR_UNSUPPORTED_DIR_IMPORT` for it. A bundler resolves both, so the read is compiled here and published as one
 * global on the page.
 *
 * THE ENTRY EXISTS ONLY FOR THE LENGTH OF THE BUILD, which is the shape `check-bundle/build.ts` established for the
 * same reason: a probe file in the tree would be scanned by every other check as if a screen had written it.
 *
 * IT CARRIES NO STYLE, AND THAT IS STRUCTURAL RATHER THAN TRUSTED. The barrel the snap arrives through imports the
 * kit's stylesheets: 30 `.css` ids reach this build's resolver, and left alone they turn a 1261-byte chunk into a
 * 12783-byte one that creates a `<style>` element carrying them, which would restyle a page whose other nine cases are
 * measured in pixels. Two things stop that. Style imports resolve to nothing, and `cssCodeSplit` is off, so a sheet
 * that does reach the graph is EXTRACTED as an asset rather than injected into the script the page runs. The build then
 * has to produce exactly one artifact, the script, and anything else is a failure rather than a file this ignores:
 * with the stub removed, that refusal names the extracted stylesheet. */

import path from "node:path";
import { build, type InlineConfig, type Plugin } from "vite";

import { frontendRoot } from "../lib/paths.ts";
import { DRAG_READ_GLOBAL } from "./weekColumns.ts";

/** The name the compiled read is written under, beside the page, so the page's tag is relative. */
export const DRAG_READ_SCRIPT = "drag-read.js";

const SPECIFIER = "syncr:drag-read";
/* A leading NUL is rollup's convention for a module no filesystem holds, and it keeps every other plugin's resolver
 * off it. */
const ENTRY_ID = `\0${SPECIFIER}`;
const NO_STYLE_ID = `\0${SPECIFIER}-no-style`;

const READ_MODULE = path.join(
  frontendRoot,
  "src",
  "ui",
  "domain",
  "week-grid",
  "useDiscreteDrag.ts",
);

/* The whole bridge: the shipped function under a name the page can call. Assigned rather than wrapped, so there is no
 * argument order here to drift from the one it is declared with. */
const ENTRY = `import { pointAt } from ${JSON.stringify(READ_MODULE)};
window.${DRAG_READ_GLOBAL} = pointAt;
`;

function entry(): Plugin {
  return {
    name: "syncr:drag-read-entry",
    enforce: "pre",
    resolveId: (id) => {
      if (id === SPECIFIER) return ENTRY_ID;
      return id.endsWith(".css") ? NO_STYLE_ID : null;
    },
    load: (id) => {
      if (id === ENTRY_ID) return ENTRY;
      return id === NO_STYLE_ID ? "" : null;
    },
  };
}

const CONFIG: InlineConfig = {
  root: frontendRoot,
  logLevel: "silent",
  plugins: [entry()],
  build: {
    write: false,
    /* OFF SO A STYLESHEET CANNOT BE INJECTED. With code splitting on, a sheet reaching the graph is written into the
     * chunk as a `<style>` element the page would then run; extracted, it is an asset this never writes and the
     * refusal below can see. */
    cssCodeSplit: false,
    /* A classic script rather than a module: a page opened over `file://` runs one without asking a server's
     * permission for it. */
    rollupOptions: { input: SPECIFIER, output: { format: "iife" } },
  },
};

/**
 * The compiled read, or a throw naming what the build produced instead.
 *
 * ONE REFUSAL RATHER THAN TWO, because one of the two could not fire. `format: "iife"` sets `codeSplitting: false`, so
 * a dynamic import is inlined and a second chunk is not reachable: a count of chunks alone had no input. What is
 * reachable is the artifact SET, which gains an extracted stylesheet the moment the style stub stops suppressing one.
 */
export async function buildDragRead(): Promise<string> {
  const result = await build(CONFIG);
  const outputs = (Array.isArray(result) ? result : [result]).filter((one) => "output" in one);
  const assets = outputs.flatMap((output) => output.output);
  const script = assets.length === 1 && assets[0].type === "chunk" ? assets[0] : null;
  if (script === null) {
    throw new Error(
      `compiling the pointer read produced ${String(assets.length)} artifact(s) rather than one script: ` +
        `${assets.map((asset) => `${asset.type} ${asset.fileName}`).join(", ")}. Style imports resolve to nothing ` +
        "here, so a stylesheet among them means the kit's own sheets reached the graph.",
    );
  }
  return script.code;
}
