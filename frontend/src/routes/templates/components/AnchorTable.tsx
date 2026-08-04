/* The commitments these rules currently type, and where each type came from.
 *
 * A RETYPE AND A RULE MATCH ARE NOT INTERCHANGEABLE, so the provenance is a column of its own rather than a
 * mark on the type. A rule match may be replaced the moment the rules are reordered; a retype was chosen for
 * the whole series and survives every rule change. A reader editing rules is deciding which of the two they are
 * looking at, and colour alone could not say it: the words do.
 *
 * AN UNMATCHED COMMITMENT IS OPAQUE BUSY TIME and says so in the type column. It casts no shadow of any kind,
 * which is the one thing a reader has to know before wondering why no prep appeared.
 *
 * THE ZONE IS STATED, NOT ASSUMED. A start reads differently in each zone, and the reader's declared home zone
 * lives on Settings, so this table renders the browser's zone and names it in the footer rather than implying
 * a fact it cannot know here. */

import { Table, type TableColumn } from "../../../ui/domain";
import { instantLabel, typeProvenanceLabel } from "../labels";
import type { Anchor } from "../../../api/hooks/useAnchors";

export interface AnchorTableProps {
  readonly anchors: readonly Anchor[];
  /** An IANA name. The caller states which zone the starts are rendered in. */
  readonly timeZone: string;
}

export function AnchorTable({ anchors, timeZone }: AnchorTableProps) {
  const columns: readonly TableColumn<Anchor>[] = [
    { key: "title", header: "Commitment", cell: (anchor) => anchor.title },
    {
      key: "startsAt",
      header: "Starts",
      cell: (anchor) => instantLabel(anchor.startsAt, timeZone),
    },
    {
      key: "type",
      header: "Type",
      cell: (anchor) => anchor.anchorTypeName ?? "untyped \u00B7 opaque busy time",
    },
    {
      key: "typeSource",
      header: "Typed by",
      cell: (anchor) => typeProvenanceLabel(anchor.typeSource),
    },
  ];

  return (
    <Table
      columns={columns}
      rows={anchors}
      rowKey={(anchor) => anchor.id}
      caption="The commitments these rules currently type"
      countLabel={(count) => `${count} commitments \u00B7 starts shown in ${timeZone}`}
    />
  );
}
