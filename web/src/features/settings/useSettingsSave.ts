import { useState } from "react";

import { ApiError } from "../../api/client";
import { useReviewSettings, useSaveReviewSettings } from "../../api/hooks";
import type { ReviewSettingsContent, ReviewSettingsVersionOut } from "../../api/types";

export const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

export const contentOf = (version: ReviewSettingsVersionOut): ReviewSettingsContent => ({
  models: version.models, screening: version.screening, fulltext: version.fulltext, default_panel: version.default_panel, editor: version.editor,
});

/** Saves the whole current settings content with one slice replaced, as the next version (409 when it moved on). */
export function useSettingsSave() {
  const settings = useReviewSettings();
  const mutation = useSaveReviewSettings();
  const [stale, setStale] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const save = async (patch: Partial<ReviewSettingsContent>, note: string): Promise<boolean> => {
    const current = settings.data?.current;
    if (!current) return false;
    setStale(null);
    setProblem(null);
    setMessage(null);
    try {
      const saved = await mutation.mutateAsync({ ...contentOf(current), ...patch, note: note.trim(), base_version: current.version });
      setMessage(`Saved as v${saved.current.version}. The next run uses it.`);
      return true;
    } catch (error) {
      if (error instanceof ApiError && error.code === "stale_version") setStale(error.message);
      else setProblem(errorText(error));
      return false;
    }
  };
  const reload = () => {
    setStale(null);
    void settings.refetch();
  };
  return { settings, save, reload, saving: mutation.isPending, stale, problem, message, setProblem };
}
