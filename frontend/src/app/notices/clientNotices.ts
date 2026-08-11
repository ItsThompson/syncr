/* WHERE A NOTICE THE CLIENT ITSELF COMPOSED IS HELD, AND WHY THE TOP BAR NEEDS A SECOND SOURCE FOR IT.
 *
 * Every other banner in this product is the api's. The words arrive on a read of the resource whose condition
 * they describe, so the banner and the panel for one condition cannot state it differently. A write the CLIENT
 * sent can fail with nothing left to say so on, and the api cannot help: it answered the request, the failure is
 * that no surface survived to receive the answer. So the sentence is composed here, and the top bar has a source
 * beside the api's.
 *
 * BANNER VOLUME, BECAUSE IT IS THE ONLY VOLUME THAT SURVIVES NAVIGATION. A reader whose form is gone has moved
 * on, and a panel belongs at the head of the affected screen: whichever screen is mounted when the answer lands
 * is not the affected one, and the reader leaves it. The list is therefore held above the outlet, by the host,
 * and a raised notice outlives every screen change until the reader answers it.
 *
 * DISMISSED BY THE READER, WHICH IS THE EXCEPTION `NoticeStrip` ALREADY CARRIES. A banner normally clears when
 * its condition clears. Nothing in the product can repair a write that did not happen, so acknowledging it is
 * the only resolution there is, and every notice from this source is rendered with `onDismiss`.
 *
 * A COMPONENT WITH NO HOST ABOVE IT RAISES NOTHING, and that is not a silent failure: the host is mounted inside
 * the gate, and outside the gate there is no top bar for a banner to occupy. Sign-in is the whole of that
 * territory and it sends no write of this kind. */

import { createContext, useContext } from "react";

import type { Notice } from "../../ui/domain";

/**
 * A notice this source can carry.
 *
 * The top bar is the only position it has, so a panel or an inline notice reaching it would render at a volume
 * its own words were not written for. Narrowing the volume here is what makes that a compile error at the call
 * site rather than a notice in the wrong place.
 */
export type BannerNotice = Notice & { readonly volume: "banner" };

export interface ClientNotices {
  /** What the client has raised and the reader has not yet answered, oldest first. */
  readonly raised: readonly BannerNotice[];
  /** Raises one. A notice replaces whatever stands under its id, so one condition stands once. */
  readonly report: (notice: BannerNotice) => void;
  readonly dismiss: (id: string) => void;
}

const NOTHING_RAISED: ClientNotices = {
  raised: [],
  report: () => undefined,
  dismiss: () => undefined,
};

export const ClientNoticeContext = createContext<ClientNotices>(NOTHING_RAISED);

/** The notices the shell is holding, or a source that carries nothing outside it. */
export function useClientNotices(): ClientNotices {
  return useContext(ClientNoticeContext);
}
