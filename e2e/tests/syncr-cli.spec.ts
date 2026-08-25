/* The `syncr` console script, driven on the host against the published port.
 *
 * THE CLI IS A CLIENT LIKE THE BROWSER. It ships in no image and no package depends on it: the
 * suite spawns the workspace's own console script on the host and points it at
 * `http://localhost:${SYNCR_E2E_PORT:-57080}`, the same origin every other scenario uses.
 *
 * THE CREDENTIAL IS OBTAINED FOR REAL. `auth login` runs the authorization-code flow with PKCE:
 * the CLI starts a loopback listener, prints the authorize URL, and waits for the browser to come
 * back with a code. This file stands where the user's browser stands -- a Playwright page carrying
 * the seeded account's session cookie opens the URL and presses Allow on the api's consent screen
 * -- so the credential this file's reads then use was minted by the real endpoints, not seeded.
 *
 * THE FALLBACK IS ASSERTED, NOT TOLERATED. A headless machine has no OS keychain, so the refresh
 * token lands in a file under an isolated XDG_CONFIG_HOME and the CLI says so on stderr. The
 * environment forces that backend failure (`PYTHON_KEYRING_BACKEND`), which makes the fallback --
 * and the notice naming it -- deterministic on every machine rather than true-by-luck in CI and
 * false on a developer's desktop.
 *
 * ONE CHECKOUT, MEASURED. The child resolves its sources through the root `.venv`'s editable
 * install, whose absolute paths point at whatever tree built that venv. Two cases pin the question
 * down: from this tree the child imports this tree's sources, and from a git worktree -- tracked
 * files but no untracked `.venv` -- the same resolution fails outright.
 */

import { execFile } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { test, expect } from "./harness.ts";
import { BASE_URL, E2E_EMAIL, E2E_PASSWORD } from "../src/config.ts";
import { SESSION_COOKIE } from "../src/api/headers.ts";
import { signIn } from "../src/api/client.ts";
import { bootstrapAccount, repoRoot, resetDatabase, tickHorizon } from "../src/harness/compose.ts";
import { resolveSyncrSource, runSyncr, spawnSyncr } from "../src/harness/syncr-cli.ts";

const run = promisify(execFile);

test.describe.configure({ mode: "serial" });

/* Where this file's invocations keep their credential: one scratch store per run, thrown away at
 * the end, so neither the developer's nor the runner's own config is ever touched. */
let storeHome: string | null = null;

/* The session cookie of the account the consent screen expects to be signed in as. */
let sessionCookieValue: string | null = null;

const cliEnvironment = (): Record<string, string> => {
  if (!storeHome) throw new Error("the scratch store was not created");
  return {
    SYNCR_API_URL: BASE_URL,
    // Points the CLI's configuration AND its fallback credential file into the scratch store.
    XDG_CONFIG_HOME: storeHome,
    // What keyring resolves to when no keychain exists; makes the fallback deterministic.
    PYTHON_KEYRING_BACKEND: "keyring.backends.fail.Keyring",
    // An inert command: nothing graphical opens anywhere, and the authorize URL is read from
    // stderr either way, because the flow states it opened or not.
    BROWSER: "/usr/bin/false",
  };
};

/** Empty the database, provision the tenant, sign the browser in, and materialize the horizon. */
test.beforeAll(async () => {
  test.setTimeout(180_000);
  await resetDatabase();
  await bootstrapAccount();
  const client = await signIn(BASE_URL, E2E_EMAIL, E2E_PASSWORD);
  sessionCookieValue = client.sessionCookie;
  await tickHorizon();
  storeHome = await mkdtemp(path.join(tmpdir(), "syncr-cli-e2e-"));
});

test.afterAll(async () => {
  if (storeHome) await rm(storeHome, { recursive: true, force: true });
  storeHome = null;
  sessionCookieValue = null;
});

/** The authorize URL the flow printed, or a failure naming everything stderr said instead. */
const waitForAuthorizeUrl = async (stderr: () => string, timeoutMs = 30_000): Promise<string> => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const stated = stderr().match(/scopes: (\S+)/);
    if (stated) return stated[1];
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`the CLI named no authorize URL within ${timeoutMs}ms. stderr:\n${stderr()}`);
};

test("auth login obtains a credential through the real authorization-code flow, consent given here", async ({
  context,
}) => {
  if (!sessionCookieValue) throw new Error("the seeded session was not created");

  const login = spawnSyncr({ args: ["auth", "login", "--json"], env: cliEnvironment() });
  const authorizeUrl = await waitForAuthorizeUrl(login.stderr);

  const page = await context.newPage();
  // The same credential in the browser as harness.ts seeds, for the same reason: the api serves
  // the consent screen to a signed-in session only.
  await context.addCookies([
    {
      name: SESSION_COOKIE,
      value: sessionCookieValue,
      url: BASE_URL,
      httpOnly: true,
      sameSite: "Lax",
      secure: true,
    },
  ]);
  await page.goto(authorizeUrl);
  await expect(page.getByRole("button", { name: "Allow" })).toBeVisible();
  await page.getByRole("button", { name: "Allow" }).click();

  // The approval's 303 lands on the CLI's loopback listener, whose plain page is what a person
  // sees; reaching it means the code was delivered.
  await expect(page.getByText("authorized")).toBeVisible();
  expect(page.url()).toContain("/callback");

  expect(await login.exited).toBe(0);
  const document = JSON.parse(login.stdout()) as {
    ok: boolean;
    data: { scopes: string[]; tokenStoreIsFallback: boolean; apiUrl: string } | null;
  };
  expect(document.ok).toBe(true);
  expect(document.data?.apiUrl).toBe(BASE_URL);
  expect(document.data?.scopes).toEqual(["plan:read", "plan:write"]);
  expect(document.data?.tokenStoreIsFallback).toBe(true);

  const notices = login.stderr();
  expect(notices).toContain("the OS keychain is not available on this machine");
  expect(notices).toContain("the refresh token is kept in");
});

test("a catalog command reads through the stored credential", async () => {
  const read = await runSyncr(["week", "show", "--json"], { env: cliEnvironment() });

  expect(read.code).toBe(0);
  const document = JSON.parse(read.stdout) as {
    ok: boolean;
    data: { isoWeek: string } | null;
  };
  expect(document.ok).toBe(true);
  expect(document.data?.isoWeek).toMatch(/^\d{4}-W\d{2}$/);
});

test("the child resolves this checkout's sources", async () => {
  const source = await resolveSyncrSource();
  expect(source.startsWith(path.join(repoRoot, "cli", "src"))).toBe(true);
});

test("in a worktree, source resolution fails outright", async ({}, testInfo) => {
  testInfo.setTimeout(120_000);
  const parent = await mkdtemp(path.join(tmpdir(), "syncr-cli-worktree-"));
  const worktree = path.join(parent, "wt");
  try {
    await run("git", ["worktree", "add", "--detach", worktree, "HEAD"], { cwd: repoRoot });
    // Tracked files only: the worktree holds pyproject.toml but not the untracked .venv, so uv
    // builds a bare environment there and the import finds nothing.
    await expect(resolveSyncrSource({ cwd: worktree })).rejects.toThrow(
      /No module named 'syncr_cli'/,
    );
  } finally {
    await run("git", ["worktree", "remove", "--force", worktree], { cwd: repoRoot }).catch(
      () => undefined,
    );
    await rm(parent, { recursive: true, force: true });
  }
});
