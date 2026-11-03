import { useEffect, useState, type FormEvent } from "react";

import { ApiError } from "../../api/client";
import { usePatchSettings, useSettings } from "../../api/hooks";

/** Admin: the email domains allowed to create an account (empty: sign-up is off). */
export function SignupDomainsForm() {
  const settings = useSettings();
  const patch = usePatchSettings();
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const saved = settings.data?.signup_domains ?? [];
  useEffect(() => setText(saved.join(", ")), [saved.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setProblem(null);
    setNotice(null);
    const domains = text.split(/[\s,;]+/).map((d) => d.trim()).filter(Boolean);
    try {
      const out = await patch.mutateAsync({ signup_domains: domains });
      setNotice((out.signup_domains ?? []).length ? "Saved. People with these email domains can create an account." : "Saved. Sign-up is off.");
    } catch (error) {
      setProblem(error instanceof ApiError ? (error.fields?.[0]?.message ?? error.message) : "Could not reach the server. Check your connection and try again.");
    }
  };
  return (
    <form onSubmit={submit} className="block">
      <h3>Sign-up</h3>
      <label className="block">Email domains allowed to create an account
        <input type="text" value={text} placeholder="company.com" aria-describedby="signup-domains-hint" onChange={(e) => setText(e.target.value)} />
        <span id="signup-domains-hint" className="hint">Separate several with commas. Use * to let anyone sign up (a closed pilot group). Leave empty to turn sign-up off; you can still invite people below.</span>
      </label>
      <p>{saved.length ? `Sign-up is on for: ${saved.join(", ")}.` : "Sign-up is off."}</p>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {notice && <p role="status">{notice}</p>}
      <button type="submit" disabled={patch.isPending}>Save sign-up domains</button>
    </form>
  );
}
