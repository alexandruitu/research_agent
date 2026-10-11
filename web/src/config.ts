/** Frontend feature switches. Hidden features keep their code; they are only left out of the navigation and the routes. */
export const FEATURES = {
  /** Alerts (scheduled re-runs and the digest inbox): hidden until the flow around them is redesigned. */
  alerts: false,
} as const;
