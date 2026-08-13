/* THE CAPTURE PREFILL A URL CARRIES: what the week screen writes, what this screen reads, and the parameters that
 * are gone once the dialog is up.
 *
 * BOTH ENDS ARE DRIVEN IN ONE FILE, because neither means anything alone. The week screen composed the URL for a
 * reader nobody landed, and a reader landed from a URL nothing writes would be a case about a string this file
 * invented. The seam case below presses the gutter label on the real week route and asserts the dialog that opens
 * on the real backlog route, through the one route table the application is built from.
 *
 * THE PREFILL IS READ OFF THE RENDERED CONTROLS, not off a draft. A value that reached the state and not the field
 * is the defect class a browser pass over this product's forms already found twice, so the Area is asserted as the
 * option text the trigger shows and the estimate as the number field's value.
 *
 * THE URL IS ASSERTED THROUGH THE ROUTER, which is why these cases build the memory router themselves rather than
 * using `renderSignedInAt`: the claim is that the parameters are gone once the dialog is open, and a reload is
 * driven by rendering again at whatever the router was left holding.
 *
 * A PARAMETER THIS SCREEN CANNOT READ IS IGNORED RATHER THAN REFUSED, which is the rule both modes in this product
 * follow: a typo in a query string is not a broken URL, and refusing one would spend a failure surface on a
 * string. What the cases here hold is that ignoring one costs nothing else in the same URL. */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RouterProvider, createMemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { jsonHandler } from "../../../testing/apiStub";
import { routes } from "../../../routes";
import { withFreshCache } from "../../../testing/renderRoute";
import {
  capturePath,
  capturePrefillIn,
  preferredWindowReading,
  withoutCapturePrefill,
} from "../../../app/capture";
import {
  buildWeekView,
  installWeekReads,
  SLOT_LABEL,
  WEEK_PATH,
} from "../../week/__tests__/fixtures";
import { AREA_CAREER, buildBacklog, buildSettings } from "./fixtures";
import { stubBacklog } from "./render";

const CAPTURE = "Capture a task";
const AREA_PLACEHOLDER = "Which Area this counts toward";
const THE_WINDOW = /slot you activated/i;

/* The slot the week fixture draws: an hour on the Wednesday, charged to Career. Written as the two instants a URL
   carries rather than derived from the fixture, because what these cases drive is a URL. */
const SLOT_FROM = "2026-02-11T14:00:00+00:00";
const SLOT_TO = "2026-02-11T15:00:00+00:00";
const SLOT_MINUTES = 60;

type Asked = Partial<Record<"capture" | "area" | "estimate" | "from" | "to", string | null>>;

/** The URL an empty slot's gutter label navigates to. An override of `null` leaves that parameter out. */
function capturePrefillPath(overrides: Asked = {}): string {
  const asked: Asked = {
    capture: "1",
    area: AREA_CAREER,
    estimate: String(SLOT_MINUTES),
    from: SLOT_FROM,
    to: SLOT_TO,
    ...overrides,
  };
  const search = new URLSearchParams();
  for (const [name, value] of Object.entries(asked)) {
    if (value !== null) search.set(name, value);
  }
  return `/backlog?${search.toString()}`;
}

interface Landing {
  /** The router itself, so the address bar is readable after the dialog opens. */
  readonly router: ReturnType<typeof createMemoryRouter>;
  /** Taking the application down, which is what makes a second landing in one case a reload. */
  readonly unmount: () => void;
}

/**
 * The real route table at a path, with the router handed back.
 *
 * `renderSignedInAt` renders the same table and is what every other case on this screen uses; these cases need the
 * router itself, and building it here is what that helper does one line at a time.
 */
async function landAt(path: string): Promise<Landing> {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const rendered = render(withFreshCache(<RouterProvider router={router} />));
  await screen.findByLabelText("Screens");
  return { router, unmount: rendered.unmount };
}

async function theCaptureForm(): Promise<HTMLElement> {
  return screen.findByRole("dialog", { name: CAPTURE });
}

/** The query a path states, which is what a router hands the screen. */
function searchIn(path: string): URLSearchParams {
  return new URL(path, window.location.origin).searchParams;
}

/** The prefill a query asks for, with the parameters this case is about set on top of a whole one. */
function prefillFor(overrides: Asked = {}) {
  return capturePrefillIn(searchIn(capturePrefillPath(overrides)));
}

const THE_SLOT = {
  areaId: AREA_CAREER,
  estimateMinutes: SLOT_MINUTES,
  preferredWindow: { from: SLOT_FROM, to: SLOT_TO },
};

describe("the URL a slot writes and the prefill it reads back", () => {
  /* THE ROUND TRIP IS THE SEAM'S OWN PROPERTY, and it is one case rather than two because a parameter renamed on
     one side of it is exactly what this has to catch: asserting the spelling here as a literal would pass a
     rename that broke the flow, since the literal would be renamed with it. */
  it("reads back everything the week screen put in it", () => {
    expect(capturePrefillIn(searchIn(capturePath(THE_SLOT)))).toEqual(THE_SLOT);
  });

  it("names the screen a task is authored on", () => {
    expect(capturePath(THE_SLOT).startsWith("/backlog?")).toBe(true);
  });

  it("asks for nothing where the query does not ask for capture", () => {
    expect(capturePrefillIn(new URLSearchParams())).toBeNull();
    expect(capturePrefillIn(searchIn("/backlog?area=x&estimate=60"))).toBeNull();
  });

  /* AN EXACT VALUE RATHER THAN PRESENCE. `capture` is an ordinary word, so a parameter that arrived from somewhere
     else meaning something else must not open a dialog over the reader's list. */
  it.each(["0", "true", "2", ""])("is not asked by capture=%s", (value) => {
    expect(capturePrefillIn(searchIn(capturePrefillPath({ capture: value })))).toBeNull();
  });

  it("is not asked by a query with no capture parameter in it at all", () => {
    expect(capturePrefillIn(searchIn(capturePrefillPath({ capture: null })))).toBeNull();
  });

  it.each([
    ["names none", null],
    ["names an empty one", ""],
  ])("carries no Area where the query %s", (_case, value: string | null) => {
    expect(prefillFor({ area: value })?.areaId).toBeUndefined();
  });

  /* AN ESTIMATE THIS CANNOT READ IS IGNORED AND THE REST OF THE PREFILL SURVIVES, which is the whole difference
     between ignoring a parameter and refusing a URL: the form opens on its own default for that member alone. */
  it.each(["soon", "", "0", "-30", "45.5", "1e3x"])(
    "reads no estimate from estimate=%s and keeps the Area",
    (value) => {
      const prefill = prefillFor({ estimate: value });

      expect(prefill?.estimateMinutes).toBeUndefined();
      expect(prefill?.areaId).toBe(AREA_CAREER);
    },
  );

  it("reads no estimate where the query states none", () => {
    expect(prefillFor({ estimate: null })?.estimateMinutes).toBeUndefined();
  });

  it("reads the estimate a figure states", () => {
    expect(prefillFor({ estimate: "90" })?.estimateMinutes).toBe(90);
  });

  /* BOTH ENDS OR NEITHER. One instant is a moment and a preferred time needs a stretch, and an end at or before
     its start is not one either: a form stating `15:00 to 14:00` would be reading a window back at the reader
     that no solver could prefer. */
  it.each([
    ["only a start", { to: null }],
    ["only an end", { from: null }],
    ["an empty end", { to: "" }],
    ["a start that is not an instant", { from: "tuesday afternoon" }],
    ["an end that is not an instant", { to: "later" }],
    ["an end before its start", { to: "2026-02-11T13:00:00+00:00" }],
    ["an end equal to its start", { to: SLOT_FROM }],
  ])("reads no window from %s", (_case, asked: Asked) => {
    const prefill = prefillFor(asked);

    expect(prefill?.preferredWindow).toBeUndefined();
    expect(prefill?.estimateMinutes).toBe(SLOT_MINUTES);
  });

  it("leaves a parameter it does not own where it found it", () => {
    const left = withoutCapturePrefill(searchIn(`${capturePath(THE_SLOT)}&week=2026-W07`));

    expect(left.toString()).toBe("week=2026-W07");
  });

  it("clears every parameter it does own", () => {
    expect(withoutCapturePrefill(searchIn(capturePath(THE_SLOT))).toString()).toBe("");
  });
});

describe("the window as the form states it", () => {
  it("reads both ends on the reader's own wall clock", () => {
    expect(preferredWindowReading({ from: SLOT_FROM, to: SLOT_TO }, "Europe/London")).toBe(
      "2026-02-11 14:00 to 2026-02-11 15:00",
    );
  });

  it("reads a window whose ends fall on two dates as two dates", () => {
    expect(
      preferredWindowReading(
        { from: "2026-02-11T23:30:00+00:00", to: "2026-02-12T00:30:00+00:00" },
        "Europe/London",
      ),
    ).toBe("2026-02-11 23:30 to 2026-02-12 00:30");
  });

  /* NOTHING TO SAY RATHER THAN A PAIR OF FAILURES. A zone the runtime does not know and an instant that is not one
     both reach this, and a form is better carrying no sentence than one reading `null to null`.

     THE END IS READ TOO, and its own case is here because it was measured missing: the reading and the
     declaration answer from one reading of the two instants, and with only the cases that spoil the START,
     dropping the guard on the END left every case on both of them green. */
  it("states nothing where the zone or an instant cannot be read", () => {
    expect(preferredWindowReading({ from: SLOT_FROM, to: SLOT_TO }, "Mars/Olympus")).toBeNull();
    expect(preferredWindowReading({ from: "soon", to: SLOT_TO }, "Europe/London")).toBeNull();
    expect(preferredWindowReading({ from: SLOT_FROM, to: "whenever" }, "Europe/London")).toBeNull();
  });
});

/** What the Area control shows, which is the option's text rather than the identifier behind it. */
function theAreaControl(dialog: HTMLElement): HTMLElement {
  return within(dialog).getByRole("combobox", { name: /Area/ });
}

function theEstimateField(dialog: HTMLElement): HTMLElement {
  return within(dialog).getByRole("spinbutton", { name: /Estimate/ });
}

describe("landing on the capture URL an empty slot writes", () => {
  it("opens capture on the slot's Area, on its own length, and states the window it runs in", async () => {
    stubBacklog({ backlog: buildBacklog() });

    await landAt(capturePrefillPath());
    const dialog = await theCaptureForm();

    expect(theAreaControl(dialog)).toHaveTextContent("Career");
    expect(theEstimateField(dialog)).toHaveValue(SLOT_MINUTES);
    expect(
      within(dialog).getByText(THE_WINDOW),
      "the window the URL carried reached no rendered surface, so a reader cannot tell it arrived",
    ).toHaveTextContent("2026-02-11 14:00 to 2026-02-11 15:00");
  });

  /* THE WINDOW IS READ IN THE READER'S OWN ZONE, which is why the host formats it and the form does not: the two
     instants name one moment, and the wall clock they read as is the reader's. A reader in Madrid activated the
     slot their own week screen drew at 15:00. */
  it("reads the window in the reader's own zone rather than in UTC", async () => {
    stubBacklog({ settings: buildSettings({ homeZone: "Europe/Madrid" }) });

    await landAt(capturePrefillPath());
    const dialog = await theCaptureForm();

    await waitFor(() => {
      expect(within(dialog).getByText(THE_WINDOW)).toHaveTextContent(
        "2026-02-11 15:00 to 2026-02-11 16:00",
      );
    });
  });

  /* A PREFILL THAT ARRIVES ALREADY REFUSED IS NOT A PREFILL. The api's default minimum chunk is fifteen minutes, so
     a slot shorter than one arrives as an estimate the form refuses on a row nobody has touched, with the submit
     disabled and nothing the reader did to fix.

     THE COUNT IS READ WITH ITS OWN CONTROL, because a class that no longer exists reads as zero refusals however
     many the form is stating: the second half of this case drives one refusal onto the same selector. */
  it("opens with nothing refused, even for a slot shorter than the default minimum chunk", async () => {
    stubBacklog();

    await landAt(capturePrefillPath({ estimate: "10" }));
    const dialog = await theCaptureForm();

    expect(theEstimateField(dialog)).toHaveValue(10);
    expect(within(dialog).getByRole("spinbutton", { name: /Minimum chunk/ })).toHaveValue(10);
    expect(dialog.querySelectorAll(".form-row__message--error")).toHaveLength(0);

    const chunk = within(dialog).getByRole("spinbutton", { name: /Minimum chunk/ });
    await userEvent.clear(chunk);
    await userEvent.type(chunk, "30");
    await userEvent.tab();

    expect(dialog.querySelectorAll(".form-row__message--error")).toHaveLength(1);
  });

  it("clears the parameters once capture is open", async () => {
    stubBacklog();

    const landed = await landAt(capturePrefillPath());
    await theCaptureForm();

    await waitFor(() => {
      expect(landed.router.state.location.search).toBe("");
    });
    expect(landed.router.state.location.pathname).toBe("/backlog");
    expect(await theCaptureForm()).toBeInTheDocument();
  });

  /* THE RELOAD ITSELF, driven the way a reload arrives: a fresh application at whatever the address bar was left
     holding. The case above says the parameters are gone; this one says what that buys, which is a reader coming
     back to the Backlog rather than to a dialog they have already dealt with. */
  it("opens nothing when the reader lands again on what the clearing left behind", async () => {
    stubBacklog();
    const landed = await landAt(capturePrefillPath());
    await theCaptureForm();
    await waitFor(() => {
      expect(landed.router.state.location.search).toBe("");
    });
    const left = `${landed.router.state.location.pathname}${landed.router.state.location.search}`;
    landed.unmount();

    await landAt(left);

    await screen.findByRole("table", { name: "The backlog" });
    expect(screen.queryByRole("dialog", { name: CAPTURE })).toBeNull();
  });

  it("opens nothing on a Backlog the reader navigated to themselves", async () => {
    stubBacklog();

    await landAt("/backlog");

    await screen.findByRole("table", { name: "The backlog" });
    expect(screen.queryByRole("dialog", { name: CAPTURE })).toBeNull();
  });

  /* WHERE FOCUS GOES ON CLOSE IS NOT THIS OPENING'S TO NAME. The control that asked for it is on the screen the
     reader has left, so there is nothing to go back to: the host's fallback of reading `document.activeElement`
     would name the document body, and driving focus onto the body suppresses the dialog family's own restoration
     to land the reader nowhere. Read through the body's own `focus`, which is how `Dialog.test.tsx` holds the same
     distinction. */
  it("drives focus onto nothing when a capture the URL opened is dismissed", async () => {
    stubBacklog();
    const focusOnBody = vi.spyOn(document.body, "focus");
    await landAt(capturePrefillPath());
    await theCaptureForm();

    await userEvent.keyboard("{Escape}");
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: CAPTURE })).toBeNull();
    });

    expect(focusOnBody).not.toHaveBeenCalled();
    focusOnBody.mockRestore();
  });

  it("ignores an estimate that is not a figure and keeps the rest of the prefill", async () => {
    stubBacklog();

    await landAt(capturePrefillPath({ estimate: "soon" }));
    const dialog = await theCaptureForm();

    expect(theEstimateField(dialog)).toHaveValue(30);
    expect(theAreaControl(dialog)).toHaveTextContent("Career");
  });

  it("states no window when the URL carries only one end of one", async () => {
    stubBacklog();

    await landAt(capturePrefillPath({ to: null }));
    const dialog = await theCaptureForm();

    expect(within(dialog).queryByText(THE_WINDOW)).toBeNull();
    expect(theAreaControl(dialog)).toHaveTextContent("Career");
  });

  /* THE FIELD THAT MUST NOT BE HERE, ASSERTED ON THE OPENING THAT CARRIES A WINDOW. `capture.test.tsx` already holds
     this property, and it drives the `n` opening: the statement below does not exist on that opening, so that case
     cannot answer about it. A window arriving is exactly the pressure that would turn the statement into a control,
     and there is still nowhere for an edited one to go -- the request shape refuses the member.

     MEASURED: labelling the statement `Preferred window` leaves the case in `capture.test.tsx` green and reddens
     this one. */
  it("offers no control for the window it states", async () => {
    stubBacklog();

    await landAt(capturePrefillPath());
    const dialog = await theCaptureForm();

    expect(within(dialog).getByText(THE_WINDOW)).toBeInTheDocument();
    for (const label of [/preferred/i, /window/i, /time of day/i]) {
      expect(within(dialog).queryByRole("textbox", { name: label })).toBeNull();
      expect(within(dialog).queryByRole("spinbutton", { name: label })).toBeNull();
      expect(within(dialog).queryByRole("combobox", { name: label })).toBeNull();
      expect(within(dialog).queryByLabelText(label)).toBeNull();
    }
  });
});

describe("the n binding", () => {
  it("still opens capture with nothing prefilled", async () => {
    stubBacklog();
    await landAt("/backlog");
    await screen.findByRole("table", { name: "The backlog" });

    await userEvent.keyboard("n");
    const dialog = await theCaptureForm();

    expect(theAreaControl(dialog)).toHaveTextContent(AREA_PLACEHOLDER);
    expect(theEstimateField(dialog)).toHaveValue(30);
    expect(within(dialog).queryByText(THE_WINDOW)).toBeNull();
  });
});

describe("the seam, from the gutter label to the prefilled form", () => {
  /* THE ONE CASE THAT MEASURES THE TWO ENDS TOGETHER, and the reason both live in one module: a rename on either
     side is a flow that silently stops working. The write still navigates, the read still opens nothing, and every
     case on either side of the seam stays green.
   *
   * THE AREA IS THE WEEK PAYLOAD'S OWN, not this file's: the Areas read here is the week fixture's, whose
     identifiers differ from the backlog fixture's, so `Career` on the trigger is the identifier having survived
     the URL. A dropped one shows the placeholder. */
  it("presses the label on the week screen and lands in a prefilled capture", async () => {
    apiServer.use(jsonHandler("/api/v1/tasks", { status: 200, body: buildBacklog() }));
    installWeekReads(buildWeekView());
    await landAt(WEEK_PATH);

    await userEvent.click(await screen.findByRole("button", { name: SLOT_LABEL }));

    const dialog = await theCaptureForm();
    expect(theAreaControl(dialog)).toHaveTextContent("Career");
    expect(theEstimateField(dialog)).toHaveValue(SLOT_MINUTES);
    expect(within(dialog).getByText(THE_WINDOW)).toHaveTextContent(
      "2026-02-11 14:00 to 2026-02-11 15:00",
    );
  });
});
