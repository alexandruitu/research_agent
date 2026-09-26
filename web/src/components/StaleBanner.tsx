import { useStale } from "../api/queryClient";

export function StaleBanner() {
  return useStale() ? <p role="status" className="stale-banner">Data may be out of date: the last refresh failed.</p> : null;
}
