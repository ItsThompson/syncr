/* An accordion. Radix's, with `[ + ]` and `[ - ]` for disclosure.
 *
 * The mark is generated content keyed on the trigger's `data-state`, which is the kit's assignment of the
 * glyph-slot channel: see `glyphs.css`. `aria-expanded` on the trigger is what a screen reader reads, so
 * the mark is hidden from it.
 *
 * `canExpandMany` is the one behavioural choice a caller makes. A Templates screen with several sections
 * open at once is the case that needs it; a settings group where one answer at a time is the point does not. */

import type { ReactNode, Ref } from "react";
import * as RadixAccordion from "@radix-ui/react-accordion";

import "./Accordion.css";
import "./glyphs.css";

export interface AccordionSection {
  readonly value: string;
  readonly label: string;
  /** Rendered at the right edge. Zero is rendered; absent means this section counts nothing. */
  readonly count?: number | undefined;
  readonly content: ReactNode;
}

export interface AccordionProps {
  readonly sections: readonly AccordionSection[];
  /** The values open now. One entry unless `canExpandMany` is set. */
  readonly openValues: readonly string[];
  readonly onOpenValuesChange: (next: readonly string[]) => void;
  readonly canExpandMany?: boolean | undefined;
  /** The accordion, which is the element a screen positions or scrolls a section into view within. */
  readonly ref?: Ref<HTMLDivElement> | undefined;
}

export function Accordion({
  sections,
  openValues,
  onOpenValuesChange,
  canExpandMany,
  ref,
}: AccordionProps) {
  const shared = sections.map((section) => (
    <RadixAccordion.Item key={section.value} value={section.value} className="accordion__item">
      <RadixAccordion.Header>
        <RadixAccordion.Trigger className="accordion__trigger">
          <span
            className="glyph glyph--bracketed glyph--disclosure accordion__mark"
            aria-hidden="true"
          />
          {section.label}
          {section.count === undefined ? null : (
            <span className="accordion__count">{section.count}</span>
          )}
        </RadixAccordion.Trigger>
      </RadixAccordion.Header>
      <RadixAccordion.Content className="accordion__panel">
        {section.content}
      </RadixAccordion.Content>
    </RadixAccordion.Item>
  ));

  /* Radix types `type` as a discriminant, so the two forms are two elements rather than one with a
   * conditional prop: `value` is a string in the single form and an array in the multiple one. */
  if (canExpandMany === true) {
    return (
      <RadixAccordion.Root
        ref={ref}
        type="multiple"
        className="accordion"
        value={[...openValues]}
        onValueChange={onOpenValuesChange}
      >
        {shared}
      </RadixAccordion.Root>
    );
  }

  return (
    <RadixAccordion.Root
      ref={ref}
      type="single"
      collapsible
      className="accordion"
      value={openValues[0] ?? ""}
      onValueChange={(next) => onOpenValuesChange(next === "" ? [] : [next])}
    >
      {shared}
    </RadixAccordion.Root>
  );
}
