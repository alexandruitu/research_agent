/** Simple (default) or Detailed paper table, remembered per user in this browser. */
export type ViewMode = "simple" | "detailed";

const key = (userId: string) => `papers.view.${userId}`;

export function readViewMode(userId: string): ViewMode {
  try {
    return window.localStorage.getItem(key(userId)) === "detailed" ? "detailed" : "simple";
  } catch {
    return "simple"; // storage blocked: the default
  }
}

export function writeViewMode(userId: string, mode: ViewMode): void {
  try {
    window.localStorage.setItem(key(userId), mode);
  } catch {
    // private mode or blocked storage: the choice lasts for this page only
  }
}
