/* `g` then a letter, the three cases in which it must do nothing, and the keystroke it consumes. */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../testing/apiServer";
import { readyz } from "../../testing/apiStub";
import { renderAt } from "../../testing/renderRoute";
import { SCREENS } from "../../ui/domain/shell/navigation";

const titleOf = (): string | null => screen.getByRole("heading", { level: 1 }).textContent;

describe("useScreenChords", () => {
  it.each(SCREENS.map((screenEntry) => [screenEntry.chord, screenEntry.label] as const))(
    "g %s reaches %s",
    async (chord, label) => {
      apiServer.use(readyz());
      renderAt("/week");

      await userEvent.keyboard(`g${chord}`);

      expect(titleOf()?.toLowerCase()).toBe(label);
    },
  );

  it("does nothing while the user is typing into a field", async () => {
    renderAt("/week");
    const field = document.createElement("input");
    document.body.append(field);
    field.focus();

    await userEvent.keyboard("gt");

    expect(titleOf()).toBe("Week");
    expect(field.value).toBe("gt");
    field.remove();
  });

  it("does nothing while the user is typing into a rich-text region", async () => {
    renderAt("/week");
    const region = document.createElement("div");
    region.setAttribute("contenteditable", "true");
    region.tabIndex = 0;
    document.body.append(region);
    region.focus();

    await userEvent.keyboard("gt");

    expect(titleOf()).toBe("Week");
    region.remove();
  });

  it("does nothing when a modifier is held, so a browser shortcut is not stolen", async () => {
    renderAt("/week");

    await userEvent.keyboard("{Meta>}g{/Meta}t");

    expect(titleOf()).toBe("Week");
  });

  it("forgets a pending g when the next key is not a screen letter", async () => {
    renderAt("/week");

    await userEvent.keyboard("gqt");

    expect(titleOf()).toBe("Week");
  });

  it("navigates on a second attempt after a forgotten prefix", async () => {
    renderAt("/week");

    await userEvent.keyboard("gq");
    await userEvent.keyboard("gb");

    expect(titleOf()).toBe("Backlog");
  });
});

/* A CHORD IS ONE GESTURE, so the keystroke that resolves it reaches no other binding. Two listeners answering one
 * keystroke is how `g c` came to confirm a day and `g ?` to open the help overlay, and the exposure is worse for a
 * route that pins: a stray pin is a hard constraint the solver then honours. The route half of this rule is
 * asserted where the route's own fixtures are, in `routes/today/__tests__/outcomes.test.tsx` and
 * `routes/week/__tests__/pinning.test.tsx`. */
describe("the keystroke that resolves a chord", () => {
  it("does not reach a shell binding: g ? opens no help overlay", async () => {
    renderAt("/week");

    await userEvent.keyboard("g?");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("still opens the help overlay when no chord is pending", async () => {
    renderAt("/week");

    await userEvent.keyboard("?");

    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
