/* THE ONE HOLDER OF THE CLIENT'S OWN BANNERS.
 *
 * MOUNTED ABOVE THE OUTLET, for the reason banner volume exists: the reader whose write failed has usually left
 * the screen that sent it, so a list held by a route would be discarded by the navigation that makes the notice
 * necessary. One holder, so two writes failing cannot each raise their own copy of the top bar.
 *
 * A NOTICE REPLACES WHATEVER STANDS UNDER ITS ID, IN THE PLACE THAT ONE ALREADY HOLDS. A condition raised twice
 * is one condition: two strips for it would be two React children under one key, and a reader would have to
 * dismiss the same sentence twice. Replacing in place rather than appending is what keeps the list oldest first,
 * so a second failure of one write does not reorder the banners a reader is already reading. */

import { useCallback, useMemo, useState, type ReactNode } from "react";

import { ClientNoticeContext, type BannerNotice, type ClientNotices } from "./clientNotices";

export interface ClientNoticeHostProps {
  readonly children: ReactNode;
}

export function ClientNoticeHost({ children }: ClientNoticeHostProps) {
  const [raised, setRaised] = useState<readonly BannerNotice[]>([]);

  const report = useCallback((notice: BannerNotice) => {
    setRaised((held) =>
      held.some((one) => one.id === notice.id)
        ? held.map((one) => (one.id === notice.id ? notice : one))
        : [...held, notice],
    );
  }, []);

  const dismiss = useCallback((id: string) => {
    setRaised((held) => held.filter((one) => one.id !== id));
  }, []);

  const source = useMemo<ClientNotices>(
    () => ({ raised, report, dismiss }),
    [raised, report, dismiss],
  );

  return <ClientNoticeContext.Provider value={source}>{children}</ClientNoticeContext.Provider>;
}
