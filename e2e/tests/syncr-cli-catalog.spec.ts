import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import type { BrowserContext } from "@playwright/test";

import { expect, test } from "./harness.ts";
import { SESSION_COOKIE } from "../src/api/headers.ts";
import { civilDateIn } from "../src/api/weeks.ts";
import { BASE_URL, HOME_ZONE } from "../src/config.ts";
import { pendingProposal } from "../src/harness/week.ts";
import { planWeek } from "../src/harness/subject-weeks.ts";
import {
  readSyncrCatalog,
  runSyncr,
  spawnSyncr,
  type SyncrCommand,
  type SyncrRun,
} from "../src/harness/syncr-cli.ts";
import { loadFixture } from "../src/seed/load.ts";

const WRAPPER_MEMBERS = ["ok", "data", "verdict", "operation", "problem"];
const DELIBERATE_TIMEOUT_TYPE = "syncr:cli-timed-out";

type JsonRecord = Record<string, unknown>;

type Block = {
  readonly id: string;
  readonly start: string;
};

type CatalogState = {
  readonly isoWeek: string;
  readonly sessionCookie: string;
  readonly storeHome: string;
  areaId?: string;
  taskId?: string;
  block?: Block;
};

type CommandDriver = () => Promise<void>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const recordAt = (value: unknown, description: string): JsonRecord => {
  if (!isRecord(value)) throw new Error(`${description} was not an object`);
  return value;
};

const textAt = (value: JsonRecord, key: string, description: string): string => {
  const stated = value[key];
  if (typeof stated !== "string") throw new Error(`${description}.${key} was not a string`);
  return stated;
};

const listAt = (value: JsonRecord, key: string, description: string): readonly unknown[] => {
  const stated = value[key];
  if (!Array.isArray(stated)) throw new Error(`${description}.${key} was not an array`);
  return stated;
};

const commandKey = ([noun, verb]: SyncrCommand): string => `${noun} ${verb}`;

const environment = (storeHome: string): Record<string, string> => ({
  SYNCR_API_URL: BASE_URL,
  XDG_CONFIG_HOME: storeHome,
  PYTHON_KEYRING_BACKEND: "keyring.backends.fail.Keyring",
  BROWSER: "/usr/bin/false",
});

const assertWrapper = (
  run: SyncrRun,
  args: readonly string[],
  expectedCode: number,
): JsonRecord => {
  expect(
    run.code,
    `${args.join(" ")} failed.\nstdout:\n${run.stdout}\nstderr:\n${run.stderr}`,
  ).toBe(expectedCode);

  const parsed: unknown = JSON.parse(run.stdout);
  const document = recordAt(parsed, `${args.join(" ")} stdout`);
  expect(Object.keys(document)).toEqual(WRAPPER_MEMBERS);
  return document;
};

const waitForAuthorizeUrl = async (stderr: () => string, timeoutMs = 30_000): Promise<string> => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const stated = stderr().match(/\bhttps?:\/\/\S+/);
    if (stated) return stated[0];
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`the CLI named no authorize URL within ${timeoutMs}ms. stderr:\n${stderr()}`);
};

test.describe.configure({ mode: "serial" });

test("every parser command drives the deployed CLI, including the deliberate timeout", async ({
  context,
}) => {
  test.setTimeout(180_000);
  const loaded = await loadFixture("reference_week");
  const storeHome = await mkdtemp(path.join(tmpdir(), "syncr-cli-catalog-e2e-"));
  const state: CatalogState = {
    isoWeek: planWeek(),
    sessionCookie: loaded.client.sessionCookie,
    storeHome,
  };

  const run = async (args: readonly string[], expectedCode = 0): Promise<JsonRecord> =>
    assertWrapper(
      await runSyncr([...args, "--json"], { env: environment(state.storeHome) }),
      args,
      expectedCode,
    );

  const login = async (): Promise<void> => {
    const invocation = spawnSyncr({
      args: ["auth", "login", "--json"],
      env: environment(state.storeHome),
    });
    const authorizeUrl = await waitForAuthorizeUrl(invocation.stderr);
    await approve(context, state.sessionCookie, authorizeUrl);
    const document = assertWrapper(
      {
        code: await invocation.exited,
        stdout: invocation.stdout(),
        stderr: invocation.stderr(),
      },
      ["auth", "login"],
      0,
    );
    expect(recordAt(document.data, "auth login data").tokenStoreIsFallback).toBe(true);
  };

  const requireArea = async (): Promise<string> => {
    if (state.areaId) return state.areaId;

    const document = await run(["task", "list"]);
    const tasks = listAt(recordAt(document.data, "task list data"), "tasks", "task list data");
    const first = recordAt(tasks[0], "task list data.tasks[0]");
    state.areaId = textAt(first, "areaId", "task list data.tasks[0]");
    return state.areaId;
  };

  const readBlock = (document: JsonRecord): void => {
    const data = recordAt(document.data, "week show data");
    if (!isRecord(data.live)) return;

    const blocks = listAt(data.live, "blocks", "week show data.live");
    const first = blocks[0];
    if (!first) return;

    const block = recordAt(first, "week show data.live.blocks[0]");
    state.block = {
      id: textAt(block, "id", "week show data.live.blocks[0]"),
      start: textAt(
        recordAt(block.interval, "week show block interval"),
        "start",
        "week show block interval",
      ),
    };
  };

  const requireBlock = (): Block => {
    if (!state.block) throw new Error("plan solve did not produce a block");
    return state.block;
  };

  const cases = new Map<string, CommandDriver>([
    ["auth login", login],
    [
      "auth status",
      async () => {
        await run(["auth", "status"]);
      },
    ],
    [
      "auth logout",
      async () => {
        await run(["auth", "logout"]);
      },
    ],
    [
      "task add",
      async () => {
        const areaId = await requireArea();
        const document = await run(["task", "add", "Catalog task", "--area", areaId]);
        state.taskId = textAt(recordAt(document.data, "task add data"), "id", "task add data");
        await run(["task", "add", "Catalog task for solve", "--area", areaId]);
      },
    ],
    [
      "task list",
      async () => {
        await requireArea();
        await run(["task", "list"]);
      },
    ],
    [
      "task done",
      async () => {
        if (!state.taskId) throw new Error("task add did not return an id");
        await run(["task", "done", state.taskId]);
      },
    ],
    [
      "backlog list",
      async () => {
        await run(["backlog", "list"]);
      },
    ],
    [
      "week show",
      async () => {
        readBlock(await run(["week", "show", "--week", state.isoWeek]));
      },
    ],
    [
      "plan show",
      async () => {
        await run(["plan", "show", "--week", state.isoWeek]);
      },
    ],
    [
      "plan solve",
      async () => {
        await run([
          "plan",
          "solve",
          "--week",
          state.isoWeek,
          "--immediate",
          "--wait",
          "--timeout",
          "30",
          "--poll-interval",
          "250",
        ]);
        readBlock(await run(["week", "show", "--week", state.isoWeek]));
        requireBlock();
      },
    ],
    [
      "plan approve",
      async () => {
        const proposal = await pendingProposal(loaded.client, state.isoWeek);
        const approval = await run(["plan", "approve", "--week", state.isoWeek], proposal ? 0 : 6);
        expect(approval.ok).toBe(proposal !== null);
        const timeout = await run(
          [
            "plan",
            "solve",
            "--week",
            state.isoWeek,
            "--wait",
            "--timeout",
            "1",
            "--poll-interval",
            "1",
          ],
          10,
        );
        const problem = recordAt(timeout.problem, "deliberate timeout problem");
        expect(problem.type).toBe(DELIBERATE_TIMEOUT_TYPE);
      },
    ],
    [
      "block done",
      async () => {
        const block = requireBlock();
        await run(["block", "done", block.id, "--week", state.isoWeek]);
      },
    ],
    [
      "block skip",
      async () => {
        const block = requireBlock();
        await run(["block", "skip", block.id, "--week", state.isoWeek]);
      },
    ],
    [
      "block partial",
      async () => {
        const block = requireBlock();
        await run(["block", "partial", block.id, "--minutes", "1", "--week", state.isoWeek]);
      },
    ],
    [
      "block move",
      async () => {
        const block = requireBlock();
        await run(["block", "move", block.id, "--to", block.start, "--week", state.isoWeek]);
      },
    ],
    [
      "day confirm",
      async () => {
        await run(["day", "confirm", civilDateIn(HOME_ZONE)]);
      },
    ],
  ]);

  try {
    const catalog = await readSyncrCatalog();
    const catalogKeys = catalog.map(commandKey);
    expect([...cases.keys()].toSorted()).toEqual(catalogKeys.toSorted());

    const logout = catalog.find((command) => commandKey(command) === "auth logout");
    if (!logout) throw new Error("the parser built no auth logout command");

    for (const command of catalog) {
      if (commandKey(command) === commandKey(logout)) continue;
      const drive = cases.get(commandKey(command));
      if (!drive)
        throw new Error(`the parser built ${commandKey(command)} without a deployment case`);
      await drive();
    }

    const logoutCase = cases.get(commandKey(logout));
    if (!logoutCase) throw new Error("the parser built auth logout without a deployment case");
    await logoutCase();
  } finally {
    await rm(storeHome, { recursive: true, force: true });
  }
});

const approve = async (
  context: BrowserContext,
  sessionCookie: string,
  authorizeUrl: string,
): Promise<void> => {
  await context.addCookies([
    {
      name: SESSION_COOKIE,
      value: sessionCookie,
      url: BASE_URL,
      httpOnly: true,
      sameSite: "Lax",
      secure: true,
    },
  ]);
  const page = await context.newPage();
  await page.goto(authorizeUrl);
  await expect(page.getByRole("button", { name: "Allow" })).toBeVisible();
  await page.getByRole("button", { name: "Allow" }).click();
  await expect(page.getByText("authorized")).toBeVisible();
};
