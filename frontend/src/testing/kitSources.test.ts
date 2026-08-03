/* WHAT COUNTS AS DRAWING WITH A CLASS, which is what three of the layer's checks rest on.
 *
 * The dead-rule check, the glyph-consumer check and the shadow-carrier enumeration all ask the same question:
 * does any component name this class. The first version asked it of the file's TEXT, and a review proved both
 * directions of the answer wrong. A comment mentioning a dead class kept it alive, which is the check written
 * to find dead rules being satisfied by a sentence about one; and the word "overlay" in a comment made a
 * component that draws no overlay one of the three surfaces carrying the shadow.
 *
 * These cases are the plants from that review, in both directions, so the blind spot is what fails if this
 * regresses. */

import { describe, expect, it } from "vitest";

import { classListsIn, namesClass } from "./kitSources";

describe("a class named in prose", () => {
  it("is not a consumer, so a comment cannot keep a dead rule alive", () => {
    const source = `/* This strip is not a .calendar__ghost, which the calendar no longer draws. */
      export function Tabs() {
        return <div className="tabs" />;
      }`;

    expect(namesClass(source, "calendar__ghost")).toBe(false);
    expect(namesClass(source, "tabs")).toBe(true);
  });

  it("is not a carrier, so a comment cannot fail an enumeration it only mentions", () => {
    const source = `// This strip is not an overlay: the domain component that floats it composes one.
      export function Tabs() {
        return <div className="tabs" />;
      }`;

    expect(namesClass(source, "overlay")).toBe(false);
  });

  it("is not a consumer when it sits in a line comment inside the markup either", () => {
    const source = `export function Tabs() {
        return (
          <div className="tabs">
            {/* a .command__row would take state-row here */}
          </div>
        );
      }`;

    expect(namesClass(source, "state-row")).toBe(false);
    expect(namesClass(source, "command__row")).toBe(false);
  });
});

describe("a class in a string that is not a class list", () => {
  it("is not a consumer, because nothing puts it on an element", () => {
    const source = `export function Tabs() {
        const message = "the overlay is drawn by the dialog";
        return <div className="tabs" title={message} />;
      }`;

    expect(namesClass(source, "overlay")).toBe(false);
  });
});

describe("a class a component actually draws with", () => {
  it("is found in a className attribute", () => {
    expect(namesClass(`<div className="overlay dialog" />`, "overlay")).toBe(true);
  });

  it("is found in either arm of a conditional class list", () => {
    const source = `<td className={day.isOutsideMonth ? "calendar__day calendar__day--outside" : "calendar__day"} />`;

    expect(namesClass(source, "calendar__day--outside")).toBe(true);
    expect(namesClass(source, "calendar__day")).toBe(true);
  });

  it("is found in a class composer's variant map, which is where a rank lives", () => {
    const source = `const button = cva("button", {
        variants: { rank: { primary: "", secondary: "button--secondary" } },
      });`;

    expect(namesClass(source, "button--secondary")).toBe(true);
  });

  it("is matched as a whole word, so one class does not answer for another", () => {
    const source = `<div className="state-rows tabs__count" />`;

    expect(namesClass(source, "state-row")).toBe(false);
    expect(namesClass(source, "tabs__count")).toBe(true);
  });
});

describe("the class lists a source writes", () => {
  it("are the attribute's and the composer's, and nothing from prose", () => {
    const source = `/* mentions className="ghost" in a comment */
      const field = cva("control control--figure");
      export function Field() {
        return <input className="date-picker__field" />;
      }`;

    expect(classListsIn(source).toSorted()).toEqual([
      "control control--figure",
      "date-picker__field",
    ]);
  });
});
