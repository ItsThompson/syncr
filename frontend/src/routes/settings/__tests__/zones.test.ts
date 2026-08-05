/* The zone options a select offers, and the stored zone it must not hide.
 *
 * THE LIST IS THE RUNTIME'S OWN. What matters is not which zones are in it, which is a property of the host's
 * database, but that a stored zone the database does not list is still offered: a select that silently dropped the
 * current value would render as though a different zone were set, which is the one failure worth a test here. */

import { describe, expect, it } from "vitest";

import { zoneOptions } from "../zones";

describe("the zones a select offers", () => {
  it("offers the runtime's own list", () => {
    const options = zoneOptions("Europe/London");

    expect(options.length).toBeGreaterThan(100);
    expect(options.map((option) => option.value)).toContain("Europe/London");
    expect(options.map((option) => option.value)).toContain("Australia/Lord_Howe");
  });

  it("labels each zone by its identifier, because an identifier is what the api stores", () => {
    expect(
      zoneOptions("Europe/London").find((option) => option.value === "Europe/London")?.label,
    ).toBe("Europe/London");
  });

  /* `Intl.supportedValuesOf` enumerates canonical zones only, so `UTC` is absent from it while the same runtime
   * resolves it. It is also the api's own default home zone, so a brand-new tenant meets this case first. */
  it("offers a resolvable zone the enumerated list omits, first and unmarked", () => {
    const options = zoneOptions("UTC");

    expect(options.at(0)).toEqual({ value: "UTC", label: "UTC" });
  });

  it("offers a stored zone the runtime cannot resolve, first and marked", () => {
    const options = zoneOptions("Mars/Olympus");

    expect(options.at(0)?.value).toBe("Mars/Olympus");
    expect(options.at(0)?.label).toContain("not in this browser's zone database");
  });

  /* An empty value is what a form starts from before a zone has been chosen. A select offering one would let a
   * reader choose nothing and call it a zone. */
  it("offers no empty option for a form that has not chosen yet", () => {
    expect(zoneOptions("").map((option) => option.value)).not.toContain("");
  });

  it("does not offer a listed zone twice", () => {
    const values = zoneOptions("Europe/London").map((option) => option.value);

    expect(new Set(values).size).toBe(values.length);
  });
});
