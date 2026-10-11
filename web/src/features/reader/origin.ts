/** Where the Reader was opened from, passed as router state so its back link returns there. */
export type ReaderOrigin = { from: "results" | "library"; back: string };

export const readerState = (from: ReaderOrigin["from"], back: string) => ({ readerOrigin: { from, back } satisfies ReaderOrigin });

export function readOrigin(state: unknown): ReaderOrigin | null {
  const origin = (state as { readerOrigin?: ReaderOrigin } | null)?.readerOrigin;
  return origin && (origin.from === "results" || origin.from === "library") && typeof origin.back === "string" && origin.back.startsWith("/") ? origin : null;
}
