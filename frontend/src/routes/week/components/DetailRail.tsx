/* THE RAIL THE DETAIL PANEL CLOSES TO, AND THE CONTROL THAT OPENS IT.
 *
 * BELOW --bp-wide THE PANEL CLOSES TO A 26px RAIL RATHER THAN NARROWING, because a narrower panel cannot hold a reason
 * and a narrower grid cannot hold a title. The rail is a reserved column either way, so the grid's own width does not
 * change when the panel opens.
 *
 * THE CONTROL IS WHAT MAKES THE RAIL MORE THAN A BORDER. On a display with no room for the panel's column the reason
 * is reachable from the keyboard by `Enter`, and the rail is the pointer's own route to it.
 *
 * THE TERTIARY RANK RATHER THAN THE QUIET ONE, because the rail is 26px and the quiet rank's own padding is 18px of it:
 * a mark inside it would sit outside the column it belongs to. */

import { PanelRightClose, PanelRightOpen } from "lucide-react";

import { Button, Icon } from "../../../ui/primitives";

export interface DetailRailProps {
  readonly isPanelOpen: boolean;
  readonly onToggle: () => void;
}

export function DetailRail({ isPanelOpen, onToggle }: DetailRailProps) {
  return (
    <div className="flex w-detail-closed shrink-0 justify-center border-l border-rule wide:hidden">
      <Button
        label={isPanelOpen ? "Close the detail panel to its rail" : "Open the detail panel"}
        onClick={onToggle}
        rank="tertiary"
      >
        <Icon mark={isPanelOpen ? PanelRightClose : PanelRightOpen} size="sm" />
      </Button>
    </div>
  );
}
