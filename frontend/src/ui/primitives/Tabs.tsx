/* Tabs. Radix's, with the active tab taking the emphasised bottom rule.
 *
 * The visual state is Radix's `data-state="active"` on the trigger, so the styling hook and the accessible
 * state are one attribute and nothing toggles a class.
 *
 * A count of zero renders as `0` rather than disappearing: a tab that vanishes when its list empties makes
 * a reader wonder whether the feature exists. `count` absent means the tab counts nothing at all, which is
 * a different statement from counting none. */

import type { ReactNode, Ref } from "react";
import * as RadixTabs from "@radix-ui/react-tabs";

import "./Tabs.css";

export interface Tab {
  readonly value: string;
  readonly label: string;
  /** Rendered beside the label. Zero is rendered; absent means this tab counts nothing. */
  readonly count?: number | undefined;
  readonly content: ReactNode;
}

export interface TabsProps {
  readonly value: string;
  readonly onValueChange: (next: string) => void;
  readonly tabs: readonly Tab[];
  /** Names the tab strip, which is what a screen reader announces before the tabs themselves. */
  readonly label: string;
  /** The strip and its panels together, which is the element a screen positions. */
  readonly ref?: Ref<HTMLDivElement> | undefined;
}

export function Tabs({ value, onValueChange, tabs, label, ref }: TabsProps) {
  return (
    <RadixTabs.Root ref={ref} value={value} onValueChange={onValueChange}>
      <RadixTabs.List className="tabs" aria-label={label}>
        {tabs.map((tab) => (
          <RadixTabs.Trigger key={tab.value} value={tab.value} className="tabs__trigger">
            {tab.label}
            {tab.count === undefined ? null : <span className="tabs__count">{tab.count}</span>}
          </RadixTabs.Trigger>
        ))}
      </RadixTabs.List>
      {tabs.map((tab) => (
        <RadixTabs.Content key={tab.value} value={tab.value} className="tabs__panel">
          {tab.content}
        </RadixTabs.Content>
      ))}
    </RadixTabs.Root>
  );
}
