import type { AvailableModelOut } from "../../api/types";

export const providerOf = (id: string | null | undefined): string | null => {
  if (!id) return null;
  const at = id.indexOf(":");
  return at > 0 ? id.slice(0, at) : null;
};

/** The provider every reviewer shares, when there are at least two and all are known; else null. */
export function sharedFamily(ids: (string | null)[]): string | null {
  if (ids.length < 2) return null;
  const providers = ids.map(providerOf);
  const first = providers[0];
  return first && providers.every((p) => p === first) ? first : null;
}

export type ModelOption = { id: string; label: string; available: boolean };

/** Available models first (sorted); the current value stays selectable, labelled with why it is not available. */
export function modelOptions(models: AvailableModelOut[], current: string | null): ModelOption[] {
  const options: ModelOption[] = models.filter((m) => m.available).map((m) => ({ id: m.id, label: m.id, available: true })).sort((a, b) => a.id.localeCompare(b.id));
  if (current && !options.some((o) => o.id === current)) {
    const known = models.find((m) => m.id === current);
    options.push({ id: current, label: `${current} (${known ? "key not accepted" : "not configured in the worker"})`, available: false });
  }
  return options;
}

const PROVIDER_NAME: Record<string, string> = { google_genai: "Gemini", anthropic: "Claude", openai: "GPT" };

/** What to do about a one-family panel: name an available model from another provider, or say how to get one. */
export function familyAdvice(family: string, models: AvailableModelOut[], reviewerName: string): string {
  const other = models.filter((m) => m.available && providerOf(m.id) !== family).sort((a, b) => a.id.localeCompare(b.id))[0];
  if (!other) return "No other provider is available yet: add a GOOGLE_API_KEY to the worker to offer Gemini models here.";
  const provider = providerOf(other.id) ?? "";
  return `Mix families: for example, make ${reviewerName} use ${other.id}${PROVIDER_NAME[provider] ? ` (${PROVIDER_NAME[provider]})` : ""}.`;
}
