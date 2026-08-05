/* Where `/` goes, which is the one decision on the root and has three answers.
 *
 * THE REDIRECT IS ASSERTED BY WHAT LANDS, not by a spy on the router: what a reader gets from `/` is a screen, and a
 * test that watched `navigate` would pass while the route table sent them somewhere that does not exist.
 *
 * THE THIRD ANSWER IS THE ONE WORTH THE TEST. A refused read is not a missing minimum: a reader whose Areas could not
 * be fetched has not lost their Areas, and sending them to setup on a 503 would be the product telling them to
 * declare what they already have. */

import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { jsonHandler, pendingHandler } from "../../testing/apiStub";
import { renderAt } from "../../testing/renderRoute";
import { MINIMUM_DECLARED, NOTHING_DECLARED, setupHandlers } from "../setup/__tests__/handlers";

const heading = async () => (await screen.findByRole("heading", { level: 1 })).textContent;

describe("the root", () => {
  it("goes to the week once the minimum a plan needs exists", async () => {
    apiServer.use(...setupHandlers(MINIMUM_DECLARED));
    renderAt("/");

    expect(await heading()).toBe("Week");
  });

  it("goes to setup while the minimum does not exist", async () => {
    apiServer.use(...setupHandlers(NOTHING_DECLARED));
    renderAt("/");

    expect(await heading()).toBe("Setup");
  });

  it("goes to setup while Areas exist and the week pattern does not", async () => {
    apiServer.use(...setupHandlers({ ...NOTHING_DECLARED, areas: 3, shapes: 2 }));
    renderAt("/");

    expect(await heading()).toBe("Setup");
  });

  it("goes to the week when a read is refused, rather than asking for what is already declared", async () => {
    apiServer.use(
      jsonHandler("/api/v1/areas", {
        status: 503,
        body: {
          type: "syncr:dependency-unavailable",
          title: "The database is unavailable",
          status: 503,
          detail: "Areas could not be read. Reading your calendars still works.",
        },
      }),
      ...setupHandlers(NOTHING_DECLARED),
    );
    renderAt("/");

    expect(await heading()).toBe("Week");
  });

  it("names what it is waiting for while the reads are outstanding, and does not spin", async () => {
    apiServer.use(
      pendingHandler("/api/v1/areas"),
      pendingHandler("/api/v1/templates"),
      pendingHandler("/api/v1/week-pattern"),
      pendingHandler("/api/v1/calendar-sources"),
    );
    renderAt("/");

    expect(await screen.findByText("Reading your setup")).toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
});
