/* THE FILTER CONTROLS. Three selects, each one a query parameter the route serves.
 *
 * PRESENTATIONAL: what each value means and which are legal is `../filters.ts`, so this file names the controls
 * and nothing about the query. Changing a filter reaches the api, which is the whole point: the at-risk
 * narrowing is the week verdict's determination and a client that made it would show a count and a row set that
 * disagree. */

import { FormRow } from "../../../ui/layout";
import { Select } from "../../../ui/primitives";
import type { BacklogFilters } from "../../../api/hooks/useBacklog";
import {
  EVERY,
  TASK_STATUSES,
  areaFilterOf,
  atRiskFilterOf,
  selectedValue,
  statusFilterOf,
} from "../filters";

export interface BacklogFilterArea {
  readonly id: string;
  readonly name: string;
}

export interface BacklogFiltersProps {
  readonly filters: BacklogFilters;
  readonly onFiltersChange: (next: BacklogFilters) => void;
  readonly areas: readonly BacklogFilterArea[];
}

const STATUS_LABELS: Record<string, string> = {
  open: "Open",
  completed: "Completed",
  dropped: "Dropped",
};

const STANDINGS = [
  { value: "true", label: "At risk" },
  { value: "false", label: "Not at risk" },
];

export function BacklogFilters({ filters, onFiltersChange, areas }: BacklogFiltersProps) {
  return (
    <div className="flex flex-wrap items-start gap-4">
      <FormRow label="Area">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            onValueChange={(next) => onFiltersChange({ ...filters, areaId: areaFilterOf(next) })}
            options={[
              { value: EVERY, label: "Every Area" },
              ...areas.map((area) => ({ value: area.id, label: area.name })),
            ]}
            value={selectedValue(filters.areaId)}
          />
        )}
      </FormRow>
      <FormRow label="Status">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            onValueChange={(next) => onFiltersChange({ ...filters, status: statusFilterOf(next) })}
            options={[
              { value: EVERY, label: "Every status" },
              ...TASK_STATUSES.map((status) => ({ value: status, label: STATUS_LABELS[status] })),
            ]}
            value={selectedValue(filters.status)}
          />
        )}
      </FormRow>
      <FormRow label="Standing">
        {(field) => (
          <Select
            describedBy={field.describedBy}
            id={field.id}
            onValueChange={(next) => onFiltersChange({ ...filters, atRisk: atRiskFilterOf(next) })}
            options={[{ value: EVERY, label: "Any standing" }, ...STANDINGS]}
            value={selectedValue(filters.atRisk)}
          />
        )}
      </FormRow>
    </div>
  );
}
