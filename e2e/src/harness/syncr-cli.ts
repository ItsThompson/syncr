/* Spawning the `syncr` console script on the host, against the published port.
 *
 * The CLI ships in no image and no package depends on it: it is an OAuth client that reaches the
 * product over HTTP like the browser does, which is why spawning it on the host needs nothing but
 * the one origin the stack publishes. The console script is resolved through the root `.venv` that
 * `uv sync --all-packages --frozen` builds -- the same environment every other workspace tool runs
 * in, invoked the same way (`uv run --no-sync`) -- and a scenario neither re-syncs nor reinstalls.
 *
 * THE CHILD MEASURES THIS CHECKOUT. A subprocess inherits none of this process's module search
 * path, so where its `syncr_cli` comes from is decided entirely by the environment it is handed:
 * the editable install in the root `.venv` points at absolute paths recorded when that venv was
 * built. `resolveSyncrSource()` asserts the child imports this tree's sources, and the suite shows
 * the same question failing outright from a git worktree, which holds the tracked files but not
 * the untracked `.venv`.
 */

import { spawn } from "node:child_process";

import { repoRoot } from "./compose.ts";

type SpawnTarget = {
  readonly args: readonly string[];
  readonly cwd?: string;
  readonly env?: Readonly<Record<string, string>>;
};

/** One running invocation: its exit, and the streams as they stand right now. */
export type SyncrProcess = {
  /** Resolves with the process's exit code, or null when a signal ended it. */
  readonly exited: Promise<number | null>;
  /** Everything written to stdout so far. The result, in this CLI's stream discipline. */
  readonly stdout: () => string;
  /** Everything written to stderr so far. Notices, including the authorize URL, arrive here
   * while the process is still waiting for the browser. */
  readonly stderr: () => string;
};

/** What one completed invocation answered with. Both streams, and what the process claimed. */
export type SyncrRun = {
  readonly code: number | null;
  readonly stdout: string;
  readonly stderr: string;
};

const spawnWorkspaceTool = ({ args, cwd, env }: SpawnTarget): SyncrProcess => {
  const child = spawn("uv", ["run", "--no-sync", ...args], {
    cwd: cwd ?? repoRoot,
    env: { ...process.env, ...env },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (chunk: string) => {
    stdout += chunk;
  });
  child.stderr.on("data", (chunk: string) => {
    stderr += chunk;
  });
  return {
    exited: new Promise((resolve, reject) => {
      child.on("error", reject);
      child.on("exit", (code) => resolve(code));
    }),
    stdout: () => stdout,
    stderr: () => stderr,
  };
};

/** One `syncr` invocation, from the same workspace environment the commands themselves use. */
export const spawnSyncr = ({ args, ...options }: SpawnTarget): SyncrProcess =>
  spawnWorkspaceTool({ args: ["syncr", ...args], ...options });

const runWorkspaceTool = async (
  args: readonly string[],
  options: Omit<SpawnTarget, "args"> = {},
): Promise<SyncrRun> => {
  const invocation = spawnWorkspaceTool({ args, ...options });
  const code = await invocation.exited;
  return { code, stdout: invocation.stdout(), stderr: invocation.stderr() };
};

/** One `syncr` invocation, running until it exits. Resolves whatever the exit code was: reading
 * the answer is the caller's business, and a non-zero exit is often exactly what is asserted. */
export const runSyncr = async (
  args: readonly string[],
  options: Omit<SpawnTarget, "args"> = {},
): Promise<SyncrRun> => runWorkspaceTool(["syncr", ...args], options);

/** Where the console script's interpreter imports `syncr_cli` from. */
export const resolveSyncrSource = async (
  options: Omit<SpawnTarget, "args"> = {},
): Promise<string> => {
  // The interpreter of the SAME console script the commands ran through, asked where its package
  // lives. A different question (a bare python, a pip listing) could answer about another env.
  const probe = await runWorkspaceTool(
    ["python", "-c", "import syncr_cli; print(syncr_cli.__file__)"],
    options,
  );
  if (probe.code !== 0) {
    throw new Error(`resolving the child's sources failed (${probe.code}).\n${probe.stderr}`);
  }
  return probe.stdout.trim();
};
