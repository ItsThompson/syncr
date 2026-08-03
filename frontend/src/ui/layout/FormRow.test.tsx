/* The form row, and the wiring it exists to make impossible to get wrong.
 *
 * A label that points at nothing and a field that is described by nothing both render correctly, which is why
 * the row mints the ids and hands them to the field rather than documenting a convention. These cases assert
 * the accessible relationships rather than the class names, because the relationships are the contract. */

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Input } from "../primitives";
import { FormRow } from "./FormRow";

function renderRow(props: Partial<Parameters<typeof FormRow>[0]> = {}) {
  return render(
    <FormRow label="Estimate" {...props}>
      {(field) => (
        <Input
          id={field.id}
          describedBy={field.describedBy}
          value="45"
          onValueChange={vi.fn<(next: string) => void>()}
        />
      )}
    </FormRow>,
  );
}

describe("the label column", () => {
  it("labels the field the row rendered, through the id the row minted", () => {
    renderRow();

    expect(screen.getByLabelText("Estimate")).toHaveValue("45");
  });

  it("marks a required row, and leaves the announcement to the field", () => {
    renderRow({ isRequired: true });

    expect(screen.getByText("*")).toBeInTheDocument();
  });
});

describe("the message under the field", () => {
  it("describes the field when it is a hint", () => {
    renderRow({ hint: "minutes, stepping by 15" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "minutes, stepping by 15",
    );
  });

  it("describes the field when it is an error", () => {
    renderRow({ error: "an estimate cannot be zero" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "an estimate cannot be zero",
    );
  });

  /* One slot, so becoming invalid changes the words rather than the row's height. */
  it("is the error and not the hint when there is both", () => {
    renderRow({ hint: "minutes, stepping by 15", error: "an estimate cannot be zero" });

    expect(screen.getByLabelText("Estimate")).toHaveAccessibleDescription(
      "an estimate cannot be zero",
    );
    expect(screen.queryByText("minutes, stepping by 15")).toBeNull();
  });

  it("takes the signal's TEXT step rather than its marker step, which fails 4.5:1", () => {
    const { container } = renderRow({ error: "an estimate cannot be zero" });

    expect(container.querySelector(".form-row__message--error")).toHaveTextContent(
      "an estimate cannot be zero",
    );
  });

  it("describes the field by nothing when there is no message at all", () => {
    renderRow();

    expect(screen.getByLabelText("Estimate")).not.toHaveAttribute("aria-describedby");
  });

  it("mints ids per row, so two rows on one screen do not both answer to one id", () => {
    const { container } = render(
      <>
        <FormRow label="Estimate" hint="minutes">
          {(field) => <input id={field.id} aria-describedby={field.describedBy} />}
        </FormRow>
        <FormRow label="Minimum chunk" hint="minutes">
          {(field) => <input id={field.id} aria-describedby={field.describedBy} />}
        </FormRow>
      </>,
    );

    const ids = [...container.querySelectorAll("input")].map((field) => field.id);
    expect(new Set(ids).size).toBe(2);
  });
});
