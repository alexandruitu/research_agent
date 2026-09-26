import { QueryCache, QueryClient } from "@tanstack/react-query";
import { useSyncExternalStore } from "react";

let stale = false;
const listeners = new Set<() => void>();
const setStale = (value: boolean) => {
  if (stale === value) return;
  stale = value;
  listeners.forEach((listener) => listener());
};

export const useStale = () =>
  useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => stale,
  );

/** A failed refetch of data that was already on screen marks the page as possibly stale until any fetch succeeds. */
export function createQueryClient(retry: number | false = 1) {
  return new QueryClient({
    queryCache: new QueryCache({
      onError: (_error, query) => {
        if (query.state.data !== undefined) setStale(true);
      },
      onSuccess: () => setStale(false),
    }),
    defaultOptions: { queries: { retry, refetchOnWindowFocus: false, staleTime: 5_000 } },
  });
}
