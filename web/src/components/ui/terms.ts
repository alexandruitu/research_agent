/**
 * Every technical word the app shows, in plain language, in one place. <Term> reads its definition here
 * and the Glossary dialog lists them all. Keep definitions short: one or two sentences, no jargon.
 */
export const GLOSSARY = {
  jev: { label: "Jev", text: "A small, fast model (from TypeSafe) that gives a probability that a paper meets a criterion. When it is confident it decides on its own; otherwise it passes the paper to the LLM." },
  escalated: { label: "escalated", text: "Jev was not confident enough, so the paper was passed to the LLM, which made the screening decision." },
  llm: { label: "LLM", text: "Large language model (for example Claude). It reads the abstract or full text and answers each criterion, quoting the sentence it relied on." },
  kappa: { label: "kappa", text: "Agreement between two raters beyond what chance alone would give: 1 is perfect agreement, 0 is no better than chance." },
  fleiss_kappa: { label: "Fleiss kappa", text: "Kappa for three or more raters: how much the reviewers agree with each other beyond chance (1 perfect, 0 chance)." },
  recall: { label: "recall", text: "Of the papers that should have been found or kept, the share the tool actually found or kept. 15/16 means one was missed." },
  coverage: { label: "coverage", text: "The share of checklist questions the reviewers could answer from the text they had. Abstracts usually answer fewer than half." },
  provisional: { label: "provisional", text: "Fewer than half of the checklist questions could be answered (usually because only the abstract was available), so no firm score is shown. Upload the full text to firm it up." },
  red_flag: { label: "red flag", text: "A serious methodological problem a reviewer found, for example no external validation or patients overlapping between training and test data." },
  editor_verdict: { label: "editor verdict", text: "The final include / exclude / uncertain call made by the editor model after reading all reviewers' answers." },
  panel_score: { label: "panel score", text: "A 0–100 score computed by code from the reviewers' checklist answers (not chosen by a model). Shown only when at least half of the checklist was answered." },
  partial_search: { label: "partial search", text: "At least one literature source did not answer (for example it was rate limited) and was skipped, so papers from it may be missing." },
  gold_set: { label: "gold set", text: "A reference list of papers already labelled by people (usually from a published systematic review), used to measure how well the tool does." },
  sr: { label: "systematic review (SR)", text: "A published review that searched the literature methodically and lists which studies it included. Its list serves as a gold set." },
  screening: { label: "screening", text: "Deciding from the title and abstract whether a paper is relevant, criterion by criterion, before reading it in depth." },
  criterion: { label: "inclusion / exclusion criterion", text: "A rule a paper must meet (inclusion, e.g. 'uses deep learning') or must not meet (exclusion, e.g. 'is a review') to be kept." },
  prompt_version: { label: "prompt version", text: "The version of the instructions sent to the models. Results from different prompt versions are not mixed in the cache." },
  demo_mode: { label: "demo mode", text: "Runs offline on built-in sample papers with simulated model answers: no network, no cost. Useful to try the tool, not for real results." },
  cached_call: { label: "cached call", text: "A model call whose exact question was asked before; the stored answer is reused instead of paying for it again." },
  holdout: { label: "holdout", text: "Part of the gold set kept aside and never used to tune thresholds, to check that the tuning also works on unseen papers." },
  threshold: { label: "threshold", text: "The probability Jev must reach before it decides on its own (to keep or to drop a paper); below it, the LLM decides." },
  field_version: { label: "field version", text: "A saved version of a field's topic, criteria and sources. Each run records the version it used, so results stay reproducible." },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;

export const GLOSSARY_KEYS = (Object.keys(GLOSSARY) as GlossaryKey[]).sort((a, b) =>
  GLOSSARY[a].label.localeCompare(GLOSSARY[b].label, "en", { sensitivity: "base" }),
);
