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
 * IT CARRIES NO STYLE. The barrel the snap arrives through imports the kit's stylesheets, and a bundle that injected
 * them would restyle a page whose other nine cases are measured in pixels. Style imports are resolved to nothing and
 * an emitted stylesheet is a failure rather than a file this ignores. */

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
    /* A classic script rather than a module: a page opened over `file://` runs one without asking a server's
     * permission for it. */
    rollupOptions: { input: SPECIFIER, output: { format: "iife" } },
  },
};

/** The compiled read, or a throw naming what the build produced instead. */
export async function buildDragRead(): Promise<string> {
  const result = await build(CONFIG);
  const outputs = (Array.isArray(result) ? result : [result]).filter((one) => "output" in one);
  const assets = outputs.flatMap((output) => output.output);
  const styles = assets.filter((asset) => asset.fileName.endsWith(".css"));
  if (styles.length > 0) {
    throw new Error(
      `compiling the pointer read emitted ${String(styles.length)} stylesheet(s), which would restyle the page`,
    );
  }

  const chunks = assets.filter((asset) => asset.type === "chunk");
  if (chunks.length !== 1) {
    throw new Error(
      `compiling the pointer read produced ${String(chunks.length)} chunk(s) rather than one`,
    );
  }
  return chunks[0].code;
}
