import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { apiServer } from "../../../testing/apiServer";
import { BLOCK_GYM, buildDay, buildEmptyDay } from "./fixtures";
import { onHostToday, renderToday } from "./render";

const OUTCOME = `${window.location.origin}/api/v1/blocks/:blockId/outcome`;
const GYM = "Gym \u00B7 Chest & Back";

function rowOf(title: string): HTMLElement {
  const row = screen.getByText(title).closest(".ledger__row");
  if (!(row instanceof HTMLElement)) throw new Error(`No ledger row for ${title}`);
  return row;
}

describe("the ledger cursor", () => {
  it("traverses rows with j and k, then records an exception on the chosen row", async () => {
    const blockIds: string[] = [];
    apiServer.use(
      http.put(OUTCOME, ({ params }) => {
        blockIds.push(String(params.blockId));
        return HttpResponse.json(null);
      }),
    );
    await renderToday(onHostToday(buildDay()));
    await screen.findByText(GYM);
    const user = userEvent.setup();

    await user.keyboard("jjkj");

    expect(rowOf(GYM)).toHaveAttribute("data-current", "");
    await user.keyboard("x");

    await waitFor(() => expect(blockIds).toEqual([BLOCK_GYM]));
  });

  it("leaves the cursor unset when the ledger has no rows", async () => {
    await renderToday(onHostToday(buildEmptyDay()));
    const user = userEvent.setup();

    await user.keyboard("j");

    expect(document.querySelector(".ledger__row[data-current]")).toBeNull();
  });
});
