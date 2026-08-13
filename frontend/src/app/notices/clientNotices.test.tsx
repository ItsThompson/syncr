/* THE SHELL'S SECOND NOTICE SOURCE, DRIVEN THROUGH THE REAL SHELL.
 *
 * WHAT IS ASSERTED IS THE COMPOSITION AND NOT THE STORE. A test that rendered the strips itself would pass while
 * the top bar rendered nothing: the claim is that a notice reported from a screen reaches the slot the api's own
 * banners occupy, so what is mounted here is `GatedShell`, with the gate, the push connection, the capture host,
 * the top bar and both sources exactly as the application assembles them.
 *
 * THE ONE THING THIS FILE SUPPLIES IS THE REPORTER. `ReportingScreen` is a child route of the real shell, standing
 * where the write that will report this sits: it holds the notice source's whole caller-side surface, which is one
 * call. The link beside it is how the notice is asked to outlive the screen that raised it, which is the property
 * banner volume exists for and the one a list held by a route would lose. */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, RouterProvider, createMemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { googleConnection } from "../../testing/apiStub";
import { withFreshCache } from "../../testing/renderRoute";
import { bannersInTheTopBar, titlesInTheTopBar } from "../../testing/topBar";
import { buildExpiryNotices } from "../../routes/settings/__tests__/fixtures";
import { GatedShell } from "../GatedShell";
import { useClientNotices, type ClientNotices } from "./clientNotices";
import { captureNotSavedNotice } from "./refusedWrites";
import type { Notice } from "../../ui/domain";
import type { Problem } from "../../contract";

const REPORT = "report a refused capture";
const REPORT_ANOTHER = "report a second failed write";
const LEAVE = "go to another screen";
const DISMISS = "Dismiss this notice";
const CLIENT_TITLE = "A task you captured was not saved";
const ANOTHER_TITLE = "A second write did not happen";
const SERVER_TITLE = "The plan is not reaching your calendar";

const REFUSED: Problem = {
  type: "syncr:validation-failed",
  title: "That task was not accepted",
  status: 422,
  detail: "The estimate has to be at least as long as the minimum chunk.",
};

const PROBE_PATH = "/probe/reporting";
const ELSEWHERE_PATH = "/probe/elsewhere";

/** A screen that reports one, standing where the write that will report it sits. */
function ReportingScreen() {
  const { report } = useClientNotices();

  return (
    <>
      <button
        type="button"
        onClick={() => {
          report(captureNotSavedNotice(REFUSED));
        }}
      >
        {REPORT}
      </button>
      {/* A second condition standing at the same time, which the client composes exactly one of today. It is
          built here rather than by a factory because what it is for is the dismissal being keyed to a notice:
          the reader answers the one they read, not whatever the source is holding. */}
      <button
        type="button"
        onClick={() => {
          report({ ...captureNotSavedNotice(REFUSED), id: "another-write", title: ANOTHER_TITLE });
        }}
      >
        {REPORT_ANOTHER}
      </button>
      <Link to={ELSEWHERE_PATH}>{LEAVE}</Link>
    </>
  );
}

/** The real shell, with a screen that can report a notice nested inside it. */
async function renderShell(): Promise<void> {
  const router = createMemoryRouter(
    [
      {
        element: <GatedShell />,
        children: [
          { path: PROBE_PATH, element: <ReportingScreen /> },
          { path: ELSEWHERE_PATH, element: <p>another screen</p> },
        ],
      },
    ],
    { initialEntries: [PROBE_PATH] },
  );
  render(withFreshCache(<RouterProvider router={router} />));
  await screen.findByLabelText("Screens");
}

/** The api's own banner, composed by the read the shell already makes, and waited for. */
async function withTheApisOwnBanner(): Promise<void> {
  apiServer.use(
    googleConnection({
      status: 200,
      body: {
        configured: true,
        connected: true,
        grantedScopes: [],
        notices: buildExpiryNotices(),
      },
    }),
  );
  await renderShell();
  await screen.findByText(SERVER_TITLE);
}

describe("a notice reported from a screen", () => {
  it("appears in the top bar, in oxide, naming what still works", async () => {
    await renderShell();

    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    const raised = bannersInTheTopBar();
    expect(raised).toHaveLength(1);
    expect(raised[0]).toHaveClass("notice--oxide");
    expect(raised[0].textContent).toContain(CLIENT_TITLE);
    expect(raised[0].textContent).toContain(
      "still works · your backlog, which is unchanged, capturing the task again",
    );
  });

  it("stands beside the api's own banner rather than replacing it", async () => {
    await withTheApisOwnBanner();

    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    expect(titlesInTheTopBar()).toEqual([SERVER_TITLE, CLIENT_TITLE]);
  });

  it("outlives the screen that reported it, which is what banner volume is for", async () => {
    await renderShell();
    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    await userEvent.click(screen.getByRole("link", { name: LEAVE }));

    expect(screen.getByText("another screen")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: REPORT })).toBeNull();
    expect(titlesInTheTopBar()).toEqual([CLIENT_TITLE]);
  });

  /* ONE CONDITION IS ONE BANNER. Two strips under one id would be two children under one React key, and a reader
   * would have to dismiss the same sentence twice to be rid of it. */
  it("stands once however many times it is reported", async () => {
    await renderShell();

    await userEvent.click(screen.getByRole("button", { name: REPORT }));
    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    expect(titlesInTheTopBar()).toEqual([CLIENT_TITLE]);
  });

  /* AND IT STANDS WHERE IT ALREADY STOOD. The list is oldest first, which is a claim about position and not only
   * about membership: a second failure of one write must not reorder the banners a reader is already reading. */
  it("keeps its place when it is reported again, rather than moving to the end", async () => {
    await renderShell();
    await userEvent.click(screen.getByRole("button", { name: REPORT }));
    await userEvent.click(screen.getByRole("button", { name: REPORT_ANOTHER }));

    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    expect(titlesInTheTopBar()).toEqual([CLIENT_TITLE, ANOTHER_TITLE]);
  });
});

describe("the reader dismissing it", () => {
  /* THE ONE CASE `NoticeStrip` OFFERS `onDismiss` FOR. A banner otherwise clears when its condition clears, and
   * nothing in the product can repair a write that did not happen: knowing is the whole of the resolution. */
  it("clears it, because acknowledging it is the only resolution there is", async () => {
    await renderShell();
    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    await userEvent.click(screen.getByRole("button", { name: DISMISS }));

    expect(bannersInTheTopBar()).toEqual([]);
  });

  it("is offered for the client's own notice and not for the api's", async () => {
    await withTheApisOwnBanner();

    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    const dismissable = bannersInTheTopBar().filter(
      (banner) => banner.querySelector(`[aria-label='${DISMISS}']`) !== null,
    );
    expect(dismissable.map((banner) => banner.querySelector("b")?.textContent)).toEqual([
      CLIENT_TITLE,
    ]);
  });

  it("leaves the api's own banner standing, because its condition has not cleared", async () => {
    await withTheApisOwnBanner();
    await userEvent.click(screen.getByRole("button", { name: REPORT }));

    await userEvent.click(screen.getByRole("button", { name: DISMISS }));

    expect(titlesInTheTopBar()).toEqual([SERVER_TITLE]);
  });

  it("clears the one they answered and leaves the client's other notice standing", async () => {
    await renderShell();
    await userEvent.click(screen.getByRole("button", { name: REPORT }));
    await userEvent.click(screen.getByRole("button", { name: REPORT_ANOTHER }));

    await userEvent.click(screen.getAllByRole("button", { name: DISMISS })[0]);

    expect(titlesInTheTopBar()).toEqual([ANOTHER_TITLE]);
  });
});

/* THE TOP BAR IS THE ONLY POSITION THIS SOURCE HAS, so the volume is narrowed in the type rather than checked at
 * run time. The stub below is typed from the exported interface, so widening `report` back to any notice stops the
 * directive erroring, and `tsc --noEmit` runs over `src`: an unused directive fails the typecheck. */
describe("the volume the source carries", () => {
  it("cannot be anything but a banner", () => {
    const panel: Notice = { ...captureNotSavedNotice(REFUSED), volume: "panel" };
    const reported: Notice[] = [];
    const source: Pick<ClientNotices, "report"> = {
      report: (notice) => reported.push(notice),
    };

    // @ts-expect-error a panel notice has no position in the top bar
    source.report(panel);

    expect(reported).toHaveLength(1);
  });
});

describe("a component with no host above it", () => {
  /* THE ASSERTION IS THAT THE CALL IS INERT, not that the screen stayed empty: a screen with no host renders no
   * top bar either, so "nothing appeared" was true of a source that threw as well as of one that carried the
   * notice nowhere. The default is read out of the context and called directly, which is the only shape that can
   * tell those two apart. */
  it("reports nothing and does not throw, because outside the shell there is no top bar", () => {
    const source = theSourceWithNoHost();

    expect(() => {
      source.report(captureNotSavedNotice(REFUSED));
    }).not.toThrow();
    expect(source.raised).toEqual([]);
  });
});

/** The source a component outside the shell is handed, read through a probe that renders under no host. */
function theSourceWithNoHost(): ClientNotices {
  const seen: ClientNotices[] = [];

  function Probe() {
    seen.push(useClientNotices());
    return null;
  }

  render(<Probe />);
  const source = seen.at(0);
  if (source === undefined)
    throw new Error("the probe did not render, so nothing below asserts anything");
  return source;
}
