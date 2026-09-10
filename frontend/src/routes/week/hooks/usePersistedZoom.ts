import { useCallback, useEffect, useRef, useState } from "react";

import { useSettingsPatch } from "../../../api/hooks/useSettings";

const ZOOM_WRITE_DELAY_MS = 200;

export interface PersistedZoom {
  readonly proposedHours: number;
  readonly onPickHours: (hours: number) => void;
  readonly onCycleHours: (hours: number) => void;
  readonly write: ReturnType<typeof useSettingsPatch>;
}

export function usePersistedZoom(visibleHours: number): PersistedZoom {
  const write = useSettingsPatch();
  const [pickedHours, setPickedHours] = useState<number | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestPick = useRef(0);

  const persist = useCallback(
    async (hours: number, pick: number): Promise<void> => {
      const applied = await write.submit({ visibleHours: hours });
      if (!applied && latestPick.current === pick) setPickedHours(null);
    },
    [write],
  );

  const cancelScheduledWrite = useCallback(() => {
    if (timer.current === null) return;
    clearTimeout(timer.current);
    timer.current = null;
  }, []);

  useEffect(() => cancelScheduledWrite, [cancelScheduledWrite]);

  const select = useCallback(
    (hours: number): number => {
      latestPick.current += 1;
      setPickedHours(hours);
      cancelScheduledWrite();
      return latestPick.current;
    },
    [cancelScheduledWrite],
  );

  const onPickHours = useCallback(
    (hours: number): void => {
      void persist(hours, select(hours));
    },
    [persist, select],
  );

  const onCycleHours = useCallback(
    (hours: number): void => {
      const pick = select(hours);
      timer.current = setTimeout(() => {
        timer.current = null;
        void persist(hours, pick);
      }, ZOOM_WRITE_DELAY_MS);
    },
    [persist, select],
  );

  return {
    proposedHours: pickedHours ?? visibleHours,
    onPickHours,
    onCycleHours,
    write,
  };
}
