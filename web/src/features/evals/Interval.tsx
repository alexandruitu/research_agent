/** A dot on a 0 to 1 axis with its interval; the numbers are given as text next to it, this is decoration. */
export function Interval({ value, ci, width = 160 }: { value: number | null; ci: [number, number] | null; width?: number }) {
  if (value === null) return null;
  return (
    <svg viewBox="0 0 100 12" width={width} height="16" aria-hidden="true" className="interval-svg">
      <line x1="0" y1="6" x2="100" y2="6" className="axis" />
      <line x1="50" y1="2" x2="50" y2="10" className="axis" />
      {ci && <line x1={ci[0] * 100} y1="6" x2={ci[1] * 100} y2="6" className="interval" />}
      <circle cx={value * 100} cy="6" r="3.5" className="dot" />
    </svg>
  );
}

/** A horizontal share bar (width by class, no inline styles), hidden from assistive tech. */
export function ShareBar({ share }: { share: number | null }) {
  if (share === null) return null;
  const step = Math.round(Math.max(0, Math.min(1, share)) * 20) * 5;
  return <span className="share-bar" aria-hidden="true"><span className={`share-fill w-${step}`} /></span>;
}
