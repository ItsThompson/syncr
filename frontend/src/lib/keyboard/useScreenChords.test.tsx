/* `g` then a letter, and the three cases in which it must do nothing. */

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
