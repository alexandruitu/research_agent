import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { JobOut, KeyOut, MyModelsOut, SignupIn, SignupOut, UsageOut } from "./types";

export const meKeys = {
  keys: ["me", "keys"] as const,
  models: ["me", "models"] as const,
  usage: ["me", "usage"] as const,
  signup: ["signup-status"] as const,
};

export const useMyKeys = () => useQuery({ queryKey: meKeys.keys, queryFn: () => api.get<KeyOut[]>("/me/keys") });
export const useMyModels = () => useQuery({ queryKey: meKeys.models, queryFn: () => api.get<MyModelsOut>("/me/models") });
export const useMyUsage = () => useQuery({ queryKey: meKeys.usage, queryFn: () => api.get<UsageOut>("/me/usage") });

/** Saving or deleting a key changes which models can be picked: refresh both. */
function useRefreshMine() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: meKeys.keys });
    void client.invalidateQueries({ queryKey: meKeys.models });
  };
}

export function useSaveKey() {
  const refresh = useRefreshMine();
  return useMutation({
    mutationFn: ({ provider, key }: { provider: string; key: string }) => api.put<KeyOut>(`/me/keys/${provider}`, { body: { key } }),
    onSuccess: refresh,
  });
}

export function useDeleteKey() {
  const refresh = useRefreshMine();
  return useMutation({ mutationFn: (provider: string) => api.delete(`/me/keys/${provider}`), onSuccess: refresh });
}

export const useCheckKey = () => useMutation({ mutationFn: (provider: string) => api.post<JobOut>(`/me/keys/${provider}/check`) });

export function useSaveModels() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (models: Record<string, string | null>) => api.put<MyModelsOut>("/me/models", { body: { models } }),
    onSuccess: (data) => client.setQueryData(meKeys.models, data),
  });
}

export const useSignupStatus = () =>
  useQuery({ queryKey: meKeys.signup, queryFn: () => api.get<{ open: boolean }>("/auth/signup"), retry: false });

export const useSignup = () => useMutation({ mutationFn: (body: SignupIn) => api.post<SignupOut>("/auth/signup", { body }) });
