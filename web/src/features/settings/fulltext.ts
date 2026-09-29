import type { FulltextIO } from "../../api/types";

export type FulltextSource = FulltextIO["sources"][number];

export const FULLTEXT_SOURCES: { key: FulltextSource; label: string; explain: string }[] = [
  { key: "pmc_oa", label: "PubMed Central Open Access", explain: "Fetches the full article from Europe PMC when the paper has a PMCID. Free, no contact needed." },
  { key: "unpaywall", label: "Unpaywall (legal open-access copies)", explain: "Looks up a legal open-access PDF or page by DOI. Unpaywall asks for a contact email." },
  { key: "upload", label: "PDFs uploaded by your team", explain: "Members can upload a PDF on a paper; the next run reviews it. Turn off to hide uploads." },
];

export const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

export function validateFulltext(f: FulltextIO): string[] {
  const errors: string[] = [];
  if (f.sources.includes("unpaywall") && !(f.contact ?? "").trim()) errors.push("Unpaywall needs a contact email.");
  if ((f.contact ?? "").trim() && !EMAIL.test((f.contact ?? "").trim())) errors.push("The contact must be an email address.");
  if (!Number.isInteger(f.max_chars) || f.max_chars < 2000 || f.max_chars > 200000) errors.push("Maximum length must be a whole number from 2 000 to 200 000 characters.");
  if (!Number.isInteger(f.upload_max_mb) || f.upload_max_mb < 1 || f.upload_max_mb > 30) errors.push("Upload limit must be a whole number from 1 to 30 MB.");
  return errors;
}

/** Order the sources as the pipeline tries them. */
export const orderedSources = (on: Set<FulltextSource>) => FULLTEXT_SOURCES.map((s) => s.key).filter((k) => on.has(k));
