import { useEffect, useState } from "react";

import { ApiError } from "../../api/client";
import { useMyModels, useSaveModels } from "../../api/meHooks";
import type { MyModelOption } from "../../api/types";

const PROVIDER_LABEL: Record<string, string> = { anthropic: "Anthropic", google_genai: "Google", openai: "OpenAI", xai: "xAI" };

export function optionLabel(option: MyModelOption): string {
  const name = option.id.split(":").slice(1).join(":");
  return `${PROVIDER_LABEL[option.provider] ?? option.provider} · ${name}${option.available ? "" : " (add a key first)"}`;
}

export function MyModelsTab() {
  const models = useMyModels();
  const save = useSaveModels();
  const [choices, setChoices] = useState<Record<string, string | null>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    if (models.data) setChoices(Object.fromEntries(models.data.roles.map((r) => [r.role, r.choice ?? null])));
  }, [models.data]);

  if (models.isLoading) return <p role="status">Loading…</p>;
  if (models.isError || !models.data) return <p role="alert">Could not load your models. Reload the page to try again.</p>;
  const options = models.data.options;
  const none = !options.some((o) => o.available);
  const submit = async () => {
    setProblem(null);
    setNotice(null);
    try {
      await save.mutateAsync(choices);
      setNotice("Saved. Your next search uses these models.");
    } catch (error) {
      setProblem(error instanceof ApiError ? error.message : "Could not reach the server.");
    }
  };
  return (
    <section>
      <h2>My models</h2>
      <p className="sub">Choose the AI model for each step of your searches. “Default” uses the team setting. Each search keeps the models it started with.</p>
      {none && <p className="banner banner--warn">You have no AI key yet: add one in Settings → My keys to choose a model.</p>}
      <table className="runs">
        <thead><tr><th scope="col">Step</th><th scope="col">Model</th></tr></thead>
        <tbody>
          {models.data.roles.map((role) => (
            <tr key={role.role}>
              <th scope="row"><label htmlFor={`model-${role.role}`}>{role.label}</label></th>
              <td>
                <select
                  id={`model-${role.role}`}
                  value={choices[role.role] ?? ""}
                  onChange={(e) => setChoices((c) => ({ ...c, [role.role]: e.target.value || null }))}
                >
                  <option value="">Default{role.default ? ` (${role.default})` : " (not set)"}</option>
                  {options.map((o) => <option key={o.id} value={o.id} disabled={!o.available}>{optionLabel(o)}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {notice && <p role="status">{notice}</p>}
      <div className="actions"><button type="button" onClick={submit} disabled={save.isPending}>Save my models</button></div>
    </section>
  );
}
