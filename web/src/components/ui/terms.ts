/**
 * Every technical word the app shows, in plain language, in one place. <Term> reads its definition here
 * and the Glossary dialog lists them all. Keep definitions short: one or two sentences, no jargon.
 */
export const GLOSSARY = {
  jev: { label: "Jev", text: "A small, fast AI model (from TypeSafe) that makes a first pass: for each criterion it says how likely a paper meets it. When it is sure it decides; when it is unsure it hands the paper to a larger model (the LLM)." },
  escalated: { label: "escalated", text: "Jev was not sure about this paper, so it was handed to the larger model (the LLM), which made the decision." },
  llm: { label: "LLM", text: "A large AI language model, for example Claude. It reads the abstract or the full paper and answers each question, quoting the sentence it relied on." },
  kappa: { label: "kappa", text: "Agreement between two raters beyond what chance alone would give: 1 is perfect agreement, 0 is no better than chance." },
  fleiss_kappa: { label: "Fleiss kappa", text: "Kappa for three or more raters: how much the reviewers agree with each other beyond chance (1 perfect, 0 chance)." },
  recall: { label: "recall", text: "Of the papers that should have been found, the share the tool actually found. 15 of 16 means it missed one." },
  coverage: { label: "coverage", text: "How much the reviewers could check: the share of their questions the available text answers. An abstract usually answers fewer than half." },
  provisional: { label: "provisional", text: "Too little of the paper was available to score it fairly (usually only the abstract), so the score is a first impression, not a firm one. Upload the full paper to firm it up." },
  red_flag: { label: "red flag", text: "A serious weakness in how the study was done, for example it was never tested on outside data, or the same patients appear in both training and testing." },
  editor_verdict: { label: "editor verdict", text: "The final call (keep, drop or unsure) made by the editor after reading every reviewer's report." },
  panel_score: { label: "panel score", text: "A 0–100 score computed by code from the reviewers' checklist answers (not chosen by a model). Shown only when at least half of the checklist was answered." },
  partial_search: { label: "partial search", text: "At least one literature source did not answer (for example it was rate limited) and was skipped, so papers from it may be missing." },
  gold_set: { label: "gold set", text: "A reference list of papers already labelled by people (usually from a published systematic review), used to measure how well the tool does." },
  sr: { label: "systematic review (SR)", text: "A published review that searched the literature methodically and lists which studies it included. Its list serves as a gold set." },
  screening: { label: "screening", text: "The first sort: from the title and abstract, does the paper fit your topic's rules? Papers that fit are kept and reviewed; the others are dropped." },
  criterion: { label: "inclusion / exclusion criterion", text: "A rule a paper must meet (inclusion, e.g. 'uses deep learning') or must not meet (exclusion, e.g. 'is a review') to be kept." },
  prompt_version: { label: "prompt version", text: "The version of the instructions sent to the models. Results from different prompt versions are not mixed in the cache." },
  demo_mode: { label: "demo mode", text: "Works offline on built-in sample papers with simulated model answers: no network, no cost. Useful to try the tool, not for real results." },
  cached_call: { label: "cached call", text: "A model call whose exact question was asked before; the stored answer is reused instead of paying for it again." },
  holdout: { label: "holdout", text: "Part of the gold set kept aside and never used to tune thresholds, to check that the tuning also works on unseen papers." },
  threshold: { label: "threshold", text: "The probability Jev must reach before it decides on its own (to keep or to drop a paper); below it, the LLM decides." },
  search_match: { label: "Search match", text: "Screening: does the paper fit your topic's criteria, from its title and abstract? Kept, Dropped or Unsure. It says nothing about how good the study is." },
  quality: { label: "Quality", text: "How good the study looks to the reviewers, in plain groups: Read first, Worth a look, Has problems, Not reviewed, or Not relevant (dropped at screening)." },
  team_decision: { label: "Team decision", text: "What your team decided about a saved paper: To read, Read, Useful or Rejected. Set by people, never by the models." },
  field_version: { label: "topic version", text: "A saved version of a topic's description, criteria and sources. Each search records the version it used, so results stay reproducible." },
  full_text: { label: "full text", text: "The whole paper (not just its summary) was available, so the reviewers read all of it." },
  abstract_only: { label: "abstract only", text: "Only the short summary at the top of the paper (the abstract) was available, so many questions could not be answered. Upload the PDF to review the whole paper." },
  panel: { label: "review panel", text: "The group of AI reviewers that reads each kept paper. Each one looks from one angle (for example statistics or clinical use) and does not see the others' answers." },
  reviewer: { label: "reviewer", text: "One AI reader in the review panel. It answers a fixed list of questions about the paper, each answer backed by an exact quote." },
  editor: { label: "editor", text: "The AI that reads all reviewers' reports, notes where they disagree and makes the final call." },
  search: { label: "search", text: "One pass for a topic: look for papers in the sources, keep the relevant ones (screening), have the panel review them and rank the best. Each search keeps the settings it used." },
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;

export const GLOSSARY_KEYS = (Object.keys(GLOSSARY) as GlossaryKey[]).sort((a, b) =>
  GLOSSARY[a].label.localeCompare(GLOSSARY[b].label, "en", { sensitivity: "base" }),
);
