import { useEffect, useMemo, useState } from "react";

import { fetchAnalysisExperienceV2 } from "./api";
import type { AnalysisExperienceV2 } from "./contracts";

export type ExperienceMap = Record<string, AnalysisExperienceV2 | null>;

/**
 * Load the same authority contract used by the analysis detail route for a
 * bounded list of historical records. A failed individual record is kept as
 * null so one unavailable video cannot make the whole archive unusable.
 */
export function useAnalysisExperiences(ids: string[]) {
  const key = useMemo(() => [...new Set(ids.filter(Boolean))].sort().join("\u001f"), [ids]);
  const [experiences, setExperiences] = useState<ExperienceMap>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const nextIds = key ? key.split("\u001f") : [];
    let cancelled = false;
    setError(null);
    if (!nextIds.length) {
      setExperiences({});
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }

    setLoading(true);
    void Promise.all(
      nextIds.map(async (id) => {
        try {
          return [id, await fetchAnalysisExperienceV2(id)] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    )
      .then((entries) => {
        if (cancelled) return;
        setExperiences(Object.fromEntries(entries));
        if (entries.every(([, value]) => value == null)) setError("复盘摘要暂时不可用，请稍后重试。");
      })
      .catch(() => {
        if (!cancelled) {
          setExperiences(Object.fromEntries(nextIds.map((id) => [id, null])));
          setError("复盘摘要暂时不可用，请稍后重试。");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [key]);

  return { experiences, loading, error };
}
