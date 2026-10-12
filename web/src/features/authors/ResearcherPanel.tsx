import { useEffect, useRef, useState } from "react";

import { ApiError } from "../../api/client";
import { useAuthorLookup, useJob } from "../../api/hooks";
import type { AuthorLookupResult, AuthorSearch, JobProgressData, LookupCoauthor, LookupInstitution } from "../../api/types";
import { Skeleton } from "../../components/ui/Skeleton";
import {
  asCoauthorRef, candidateWords, defaultCoauthors, GROUP_WORDS, newSpec, personOf, toggle, withGroup, type Group,
} from "./researcher";

type Props = { authors: AuthorSearch | null; onChange: (authors: AuthorSearch | null) => void; demo: boolean; disabled?: boolean };

/** A finished author_lookup job's result (undefined while it runs); `failed` carries the stored error. */
function useLookupResult(jobId: string | null) {
  const job = useJob(jobId);
  const status = job.data?.status;
  const result = status === "done" ? (((job.data?.progress ?? {}) as JobProgressData).result as AuthorLookupResult | undefined) : undefined;
  return { result, pending: !!jobId && (!job.data || status === "queued" || status === "running"), failed: status === "failed" ? (job.data?.error ?? "no details were stored.") : null };
}

const errorText = (error: unknown) => (error instanceof ApiError ? error.message : "Could not reach the server.");

/**
 * Topic editor, Researcher tab: find the person in OpenAlex (a human picks; names never identify anyone), then the
 * group searched with them: frequent co-authors (default, an editable checklist), their institution(s), or nobody.
 */
export function ResearcherPanel({ authors, onChange, demo, disabled = false }: Props) {
  const lookup = useAuthorLookup();
  const [name, setName] = useState(authors?.people[0]?.name ?? "");
  const [searchJob, setSearchJob] = useState<string | null>(null);
  const [groupJob, setGroupJob] = useState<string | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [found, setFound] = useState<{ coauthors: LookupCoauthor[]; institutions: LookupInstitution[] } | null>(null);
  const searched = useLookupResult(searchJob);
  const grouped = useLookupResult(groupJob);
  const applied = useRef<string | null>(null);
  const mode = demo ? "demo" : "live";

  useEffect(() => {
    const result = grouped.result;
    if (!groupJob || !result || result.step !== "group" || applied.current === groupJob) return;
    applied.current = groupJob;
    setFound({ coauthors: result.coauthors, institutions: result.institutions });
    onChange(withGroup(authors ?? newSpec(result.people), result.people, result.coauthors, result.institutions));
  }, [groupJob, grouped.result, authors, onChange]);

  const find = async () => {
    setProblem(null);
    setPicked([]);
    try {
      setSearchJob((await lookup.mutateAsync({ step: "search", name: name.trim(), mode })).id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const candidates = searched.result?.step === "search" ? searched.result.candidates : [];
  const applyPicked = async () => {
    const people = candidates.filter((c) => picked.includes(c.openalex_id)).map(personOf);
    if (!people.length) return;
    setProblem(null);
    setFound(null);
    onChange(newSpec(people));
    try {
      setGroupJob((await lookup.mutateAsync({ step: "group", people, mode })).id);
    } catch (error) {
      setProblem(errorText(error));
    }
  };

  const set = (patch: Partial<AuthorSearch>) => authors && onChange({ ...authors, ...patch });
  const setMin = (min: number) => {
    if (!authors || !Number.isFinite(min) || min < 1) return;
    set({ min_shared: min, ...(found ? { coauthors: defaultCoauthors(found.coauthors, min) } : {}) });
  };
  const checked = new Set((authors?.coauthors ?? []).map((c) => c.openalex_id));
  // the lookup's co-authors with their shared works, then saved ones the lookup did not list
  const listed: { ref: ReturnType<typeof asCoauthorRef>; shared: number | null }[] = [
    ...(found?.coauthors ?? []).map((c) => ({ ref: asCoauthorRef(c), shared: c.shared })),
    ...(authors?.coauthors ?? []).filter((c) => !found?.coauthors.some((f) => f.openalex_id === c.openalex_id)).map((ref) => ({ ref, shared: null })),
  ];
  const institutions = [
    ...(found?.institutions ?? []).map((i) => ({ openalex_id: i.openalex_id, name: i.name, works: i.works as number | null })),
    ...(authors?.institutions ?? []).filter((i) => !found?.institutions.some((f) => f.openalex_id === i.openalex_id)).map((i) => ({ ...i, works: null })),
  ];
  const chosenInstitutions = new Set((authors?.institutions ?? []).map((i) => i.openalex_id));
  const noS2 = !!authors && !authors.people.some((p) => p.s2_id);

  return (
    <section aria-label="Researcher search" className="researcher-panel">
      <p className="lede">Find a researcher in OpenAlex, pick the right person, then choose who else to search.</p>
      <div className="actions">
        <label>Researcher name <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Ana Popescu" disabled={disabled}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); if (name.trim()) void find(); } }} /></label>
        <button type="button" onClick={() => void find()} disabled={disabled || !name.trim() || lookup.isPending || searched.pending}>
          {searched.pending ? "Searching…" : "Find researcher"}
        </button>
        <span className="hint">{demo ? "Demo: synthetic candidates, no network." : "Searches OpenAlex authors."}</span>
      </div>
      {problem && <p role="alert" className="form-error">{problem}</p>}
      {searched.pending && <Skeleton label="the candidates" rows={2} />}
      {searched.failed && <p role="alert" className="form-error">The search failed: {searched.failed}</p>}
      {searched.result && candidates.length === 0 && <p className="sub">No OpenAlex author with this name.</p>}
      {candidates.length > 0 && (
        <fieldset className="candidates">
          <legend>Pick the person (several if OpenAlex split the same person)</legend>
          <ul className="plain-list">
            {candidates.map((c) => (
              <li key={c.openalex_id}>
                <label className="check">
                  <input type="checkbox" checked={picked.includes(c.openalex_id)} disabled={disabled}
                    onChange={(e) => setPicked(e.target.checked ? [...picked, c.openalex_id] : picked.filter((id) => id !== c.openalex_id))} />
                  <span><strong>{c.name}</strong> <span className="sub-inline">{candidateWords(c)}</span></span>
                </label>
              </li>
            ))}
          </ul>
          <button type="button" className="primary" onClick={() => void applyPicked()} disabled={disabled || picked.length === 0}>
            Use selected ({picked.length})
          </button>
        </fieldset>
      )}
      {authors && (
        <div className="researcher-group">
          <h3>Searching</h3>
          <ul className="plain-list" aria-label="People searched">
            {authors.people.map((p) => (
              <li key={p.openalex_id || p.name}>
                <strong>{p.name}</strong> <span className="sub-inline">{[p.openalex_id && `OpenAlex ${p.openalex_id}`, p.orcid ? `ORCID ${p.orcid}` : "no ORCID (PubMed and Europe PMC search by name: name matches)"].filter(Boolean).join(" · ")}</span>
              </li>
            ))}
          </ul>
          {grouped.pending && <Skeleton label="the co-authors" rows={3} />}
          {grouped.failed && <p role="alert" className="form-error">The co-author lookup failed: {grouped.failed}</p>}
          <fieldset>
            <legend>Group</legend>
            {(Object.keys(GROUP_WORDS) as Group[]).map((g) => (
              <label key={g} className="check">
                <input type="radio" name="author-group" value={g} checked={authors.group === g} disabled={disabled} onChange={() => set({ group: g })} /> {GROUP_WORDS[g]}
              </label>
            ))}
          </fieldset>
          {authors.group === "coauthors" && (
            <fieldset>
              <legend>Co-authors</legend>
              <label>At least <input type="number" min={1} max={50} size={3} value={authors.min_shared ?? 3} disabled={disabled}
                onChange={(e) => setMin(Number(e.target.value))} /> shared works</label>
              {listed.length === 0 ? (
                <p className="sub">{grouped.pending ? "Looking up co-authors…" : "No co-authors listed yet."}</p>
              ) : (
                <ul className="plain-list" aria-label="Co-authors">
                  {listed.map(({ ref, shared }) => (
                    <li key={ref.openalex_id}>
                      <label className="check">
                        <input type="checkbox" checked={checked.has(ref.openalex_id)} disabled={disabled}
                          onChange={(e) => set({ coauthors: toggle(authors.coauthors ?? [], ref, e.target.checked) })} />
                        {ref.name} <span className="sub-inline">{shared === null ? "saved" : `${shared} shared work${shared === 1 ? "" : "s"}`}</span>
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
          )}
          {authors.group === "institution" && (
            <fieldset>
              <legend>Institutions (much broader: every paper by anyone there)</legend>
              {institutions.length === 0 ? <p className="sub">No institution found for this person.</p> : (
                <ul className="plain-list" aria-label="Institutions">
                  {institutions.map((i) => (
                    <li key={i.openalex_id}>
                      <label className="check">
                        <input type="checkbox" checked={chosenInstitutions.has(i.openalex_id)} disabled={disabled}
                          onChange={(e) => set({ institutions: toggle(authors.institutions ?? [], { openalex_id: i.openalex_id, name: i.name }, e.target.checked) })} />
                        {i.name} {i.works !== null && <span className="sub-inline">{i.works} works</span>}
                      </label>
                    </li>
                  ))}
                </ul>
              )}
            </fieldset>
          )}
          <p className="hint">
            OpenAlex searches by author id; PubMed and Europe PMC by ORCID, else by name (marked “name match”).
            {noS2 ? " Semantic Scholar will be skipped: no author id was found through the ORCID." : ""} Other sources are skipped for author search, with a note on the run.
          </p>
          <button type="button" onClick={() => { setFound(null); setSearchJob(null); setGroupJob(null); onChange(null); }} disabled={disabled}>Stop searching by researcher</button>
        </div>
      )}
    </section>
  );
}
