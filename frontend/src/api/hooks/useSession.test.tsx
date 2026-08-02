/* The session read, through the generated client.
 *
 * A 401 is an answer and not a failure. Every other failure is an error, and the difference is what
 * keeps a signed-in reader out of the login flow when the api is briefly unreachable. */

import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import {
  pendingHandler,
  readyz,
  session,
  signedOutResponse,
  unreachableHandler,
} from "../../testing/apiStub";
import { renderAt } from "../../testing/renderRoute";

describe("useSession, through the gate", () => {
  it("renders the shell for a signed-in reader", async () => {
    apiServer.use(readyz());
    renderAt("/week");

    await waitFor(() => expect(screen.getByLabelText("Screens")).toBeInTheDocument());
  });

  it("sends a signed-out visitor to sign-in, carrying the route they asked for", async () => {
    apiServer.use(session(signedOutResponse));
    renderAt("/backlog");

    expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Sign in");
    expect(screen.getByText("/backlog")).toBeInTheDocument();
  });

  it("does not treat an unreachable api as signed out", async () => {
    apiServer.use(unreachableHandler("/auth/session"));
    renderAt("/week");

    expect(await screen.findByText(/The request did not complete/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { level: 1 })).not.toBeInTheDocument();
  });

  it("does not treat a server fault as signed out either", async () => {
    apiServer.use(
      session({
        status: 500,
        body: {
          type: "syncr:internal-error",
          title: "Internal server error",
          status: 500,
          detail: "The request could not be completed. Nothing was changed.",
        },
      }),
    );
    renderAt("/week");

    expect(
      await screen.findByText("The request could not be completed. Nothing was changed."),
    ).toBeInTheDocument();
  });

  it("shows a static reading while the session is being read", () => {
    apiServer.use(pendingHandler("/auth/session"));
    renderAt("/week");

    expect(screen.getByText("reading your session")).toBeInTheDocument();
  });
});
