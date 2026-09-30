/** Placeholder rows while data loads; announced once as "Loading <label>". */
export function Skeleton({ label, rows = 4 }: { label: string; rows?: number }) {
  return (
    <div className="skeleton" role="status" aria-busy="true">
      <span className="sr-only">Loading {label}…</span>
      {Array.from({ length: rows }, (_, i) => <div key={i} className={`skeleton-row skeleton-row--${(i % 3) + 1}`} aria-hidden="true" />)}
    </div>
  );
}
