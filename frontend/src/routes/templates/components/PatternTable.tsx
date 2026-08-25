/* The pattern as it stands: seven weekdays, each naming the day type it uses.
 *
 * SEVEN ROWS, ALWAYS. A weekday with no day type is a row reading `not declared` rather than an absent row: a
 * six-row table would make the missing weekday the one thing the reader cannot see, and a weekday that names
 * no day type materializes nothing at all.
 *
 * This is what is STORED. The editor beside it holds what is about to be stored, which is why both exist: a
 * form showing its own draft cannot also show what the plan is currently built from. */

import { Table, type TableColumn } from "../../../ui/domain";
import { WEEKDAY_KEYS, weekdayLabel, type Weekday } from "../labels";
import type { DayType } from "../../../api/hooks/useTemplates";
import type { WeekPattern } from "../../../api/hooks/useWeekPattern";

export interface PatternTableProps {
  /** Null until the tenant declares one, which is what the api answers 404 for. */
  readonly pattern: WeekPattern | null;
  readonly dayTypes: readonly DayType[];
}

/* THE DAY TYPE COLUMN ABSORBS THE SURPLUS. The weekday names are seven known words plus one longest cell, so the
 * weekday column holds the one width that clears them and the day type's own name takes what is left: a long day
 * type spends its own row's height instead of moving a weekday column beside it. */
const WEEKDAY_W = "88px";

export function PatternTable({ pattern, dayTypes }: PatternTableProps) {
  const columns: readonly TableColumn<Weekday>[] = [
    {
      key: "weekday",
      header: "Weekday",
      width: WEEKDAY_W,
      cell: (weekday) => weekdayLabel(weekday),
    },
    {
      key: "dayType",
      header: "Day type",
      width: { weight: 1 },
      cell: (weekday) => {
        if (pattern === null) return "not declared";
        const dayTypeId = pattern[weekday];
        return (
          dayTypes.find((dayType) => dayType.id === dayTypeId)?.name ??
          "a day type you no longer have"
        );
      },
    },
  ];

  return (
    <Table
      columns={columns}
      rows={WEEKDAY_KEYS}
      rowKey={(weekday) => weekday}
      caption="The declared week pattern"
      countLabel={(count) =>
        pattern === null ? `${count} weekdays, none mapped yet` : `${count} weekdays mapped`
      }
    />
  );
}
