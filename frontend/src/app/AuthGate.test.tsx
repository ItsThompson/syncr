/* The gate in front of the shell: four states, and the return path.
 *
 * Rendered standalone rather than through the route table, because the state under test is the
 * session resource and the router only has to supply a location. */

import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";
import { describe, expect, it } from "vitest";

import type { Session } from "../api/hooks/useSession";
import type { Problem } from "../api/problem";
import type { Resource } from "../api/resource";
import { AuthGate } from "./AuthGate";
import { DEFAULT_RETURN_PATH, returnPathFrom, signInTarget } from "./signIn";

const signedIn: Session = {
  tenantId: "1e3c9f4c-8a2e-4a1b-9a5f-3f6b2c9d1a77",
  userId: "7d2b1a90-4c6e-4f3a-8b21-5c9e0d4f6a12",
  email: "reader@example.com",
  expiresAt: "2026-08-30T09:00:00+00:00",
};

const unreachable: Problem = {
  type: "syncr:api-unreachable",
  title: "The api could not be reached",
  status: 0,
  detail: "The request did not complete. Nothing was sent, so nothing changed.",
};

function SignInProbe() {
  const location = useLocation();
  return <p>sign in, returning to {returnPathFrom(location.search)}</p>;
}

function renderGate(session: Resource<Session>, at: string) {
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route path="/sign-in" element={<SignInProbe />} />
        <Route
          path="*"
          element={
            <AuthGate session={session}>
              <p>the shell</p>
            </AuthGate>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthGate", () => {
  it("renders the shell for a session that exists", () => {
    renderGate({ status: "ready", data: signedIn }, "/week");
    expect(screen.getByText("the shell")).toBeInTheDocument();
  });

  it("renders a static reading while the session is unknown, never a spinner", () => {
    renderGate({ status: "loading" }, "/week");
    expect(screen.getByText("reading your session")).toBeInTheDocument();
    expect(screen.queryByText("the shell")).not.toBeInTheDocument();
  });

  it("redirects to sign-in when there is no session, and names where it will return", () => {
    renderGate({ status: "ready", data: null }, "/areas?mode=review");
    expect(screen.getByText(/sign in, returning to/)).toHaveTextContent("/areas?mode=review");
    expect(screen.queryByText("the shell")).not.toBeInTheDocument();
  });

  it("states a failure rather than redirecting, so a network blip does not lose the reader's place", () => {
    renderGate({ status: "error", problem: unreachable }, "/week");
    expect(screen.getByText(unreachable.detail)).toBeInTheDocument();
    expect(screen.queryByText(/sign in/)).not.toBeInTheDocument();
  });
});

describe("the return path", () => {
  it("carries the requested route, query string included", () => {
    expect(signInTarget("/week?mode=session")).toBe("/sign-in?next=%2Fweek%3Fmode%3Dsession");
  });

  it("reads back the route it carried", () => {
    expect(returnPathFrom("?next=%2Fweek%3Fmode%3Dsession")).toBe("/week?mode=session");
  });

  it("falls back to the landing screen when nothing was recorded", () => {
    expect(returnPathFrom("")).toBe(DEFAULT_RETURN_PATH);
  });

  it.each([
    "https://elsewhere.example/steal",
    "//elsewhere.example/steal",
    "javascript:alert(1)",
    // The four a first-two-characters check accepts. The URL parser normalises a backslash to a
    // slash and strips tab and newline BEFORE parsing, so each of these resolves to another origin
    // while still starting with a single slash.
    String.raw`/\elsewhere.example/steal`,
    String.raw`/\/elsewhere.example`,
    "/\t/elsewhere.example/steal",
    "/\n/elsewhere.example/steal",
  ])("refuses %j, so a crafted value cannot redirect off-site", (crafted) => {
    expect(returnPathFrom(`?next=${encodeURIComponent(crafted)}`)).toBe(DEFAULT_RETURN_PATH);
  });

  /* The guard's own claim, checked against the parser the browser uses rather than against the
   * guard's reasoning. A value that survives must resolve to the origin it was resolved against. */
  it.each([
    "/week",
    "/week?mode=session",
    "/areas?mode=review",
    "/backlog#top",
    "/settings?next=%2Fweek",
  ])("keeps %j, which resolves on-origin", (local) => {
    const kept = returnPathFrom(`?next=${encodeURIComponent(local)}`);

    expect(kept).toBe(local);
    expect(new URL(kept, "https://syncr.example").origin).toBe("https://syncr.example");
  });

  it("refuses every accepted value that resolves off-origin, checked by resolution", () => {
    const hostile = [
      "https://elsewhere.example/steal",
      "//elsewhere.example/steal",
      String.raw`/\elsewhere.example/steal`,
      String.raw`/\/elsewhere.example`,
      "/\t/elsewhere.example/steal",
      "/\n/elsewhere.example/steal",
    ];

    for (const crafted of hostile) {
      const kept = returnPathFrom(`?next=${encodeURIComponent(crafted)}`);
      expect(new URL(kept, "https://syncr.example").origin).toBe("https://syncr.example");
    }
  });
});
