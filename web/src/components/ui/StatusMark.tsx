export const LIBRARY_STATUSES = ["to_read", "read", "relevant", "rejected"] as const;
export type LibraryStatus = (typeof LIBRARY_STATUSES)[number];
export const STATUS_META: Record<LibraryStatus, { icon: string; word: string }> = {
  to_read: { icon: "○", word: "To read" },
  read: { icon: "◐", word: "Read" },
  relevant: { icon: "★", word: "Useful" }, // API value stays `relevant`
  rejected: { icon: "⊘", word: "Rejected" },
};
export const statusMeta = (status: string) => STATUS_META[status as LibraryStatus] ?? { icon: "·", word: status.replace(/_/g, " ") };

/** A library status as an icon and a word (never colour alone). */
export function StatusMark({ status }: { status: string }) {
  const { icon, word } = statusMeta(status);
  return (
    <span className={`status-mark status-mark--${status}`}>
      <span aria-hidden="true">{icon}</span> {word}
    </span>
  );
}
