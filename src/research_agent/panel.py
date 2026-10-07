"""Default review panel (seeded into the web app, editable there). Item tags name the CLAIM 2020 or
TRIPOD+AI item each question comes from; weights 1-3; red_flag_if marks answers that must be surfaced,
flag_text says how such a flag reads (the problem, not the item)."""

import copy

FLAG_TEXT = {
    "m1": "Study design or data sources not stated",
    "m2": "Eligibility criteria not stated",
    "m3": "Data not split by patient (possible leakage)",
    "m4": "Data partitioning not described",
    "m5": "No external validation",
    "m6": "Reference standard not defined",
    "m7": "Annotators not described",
    "m8": "Preprocessing may have seen test data",
    "m9": "Test set used for model selection or tuning",
    "m10": "Missing data not described",
    "c1": "Clinical question not stated",
    "c2": "Population does not match the intended use",
    "c3": "Patient characteristics not reported",
    "c4": "Reference standard not the one used in practice",
    "c5": "Imaging acquisition not described",
    "c6": "No comparison with clinicians or standard of care",
    "c7": "Model failures not analysed",
    "c8": "Clinical workflow not discussed",
    "c9": "Limitations not discussed",
    "s1": "No confidence intervals for performance",
    "s2": "Sample size not justified",
    "s3": "Patient and image counts not reported",
    "s4": "Calibration not assessed",
    "s5": "Missing data not quantified",
    "s6": "No subgroup performance",
    "s7": "Statistical tests not named",
    "s8": "Class imbalance not addressed",
    "s9": "Threshold may have been tuned on the test set",
    "s10": "No robustness or sensitivity analysis",
}


def _item(key, text, source, weight=1, red_flag_if=None, pass_if="yes"):
    return {
        "key": key,
        "text": text,
        "weight": weight,
        "source": source,
        "pass_if": pass_if,
        "red_flag_if": red_flag_if,
        "flag_text": FLAG_TEXT[key],  # how the item reads when it raises a red flag
    }


DEFAULT_PANEL = (
    {
        "key": "methodologist",
        "name": "Methodologist",
        "version": 1,
        "model": None,
        "perspective": (
            "You review study design and data handling of medical imaging AI studies: data sources, "
            "eligibility, how data were partitioned, leakage between training and test data, external "
            "validation and the reference standard."
        ),
        "items": [
            _item(
                "m1",
                "The study design (prospective or retrospective) and the data sources are stated.",
                "CLAIM 2020 #5",
            ),
            _item("m2", "Eligibility criteria for patients or images are stated.", "CLAIM 2020 #8"),
            _item(
                "m3",
                "Data were partitioned at patient level, so no patient appears in more than one of "
                "the training, validation and test sets.",
                "CLAIM 2020 #21",
                3,
                "no",
            ),
            _item(
                "m4",
                "How data were assigned to training, validation and test sets is described.",
                "CLAIM 2020 #20",
                2,
            ),
            _item(
                "m5",
                "The model was tested on external data from a different site, scanner or period than "
                "the training data.",
                "CLAIM 2020 #32",
                3,
                "no",
            ),
            _item("m6", "The reference standard (ground truth) is defined.", "CLAIM 2020 #14", 2),
            _item(
                "m7",
                "Who annotated the reference standard, and their qualifications, are described.",
                "CLAIM 2020 #16",
            ),
            _item(
                "m8",
                "Preprocessing and feature selection were fitted on training data only.",
                "CLAIM 2020 #9",
                2,
            ),
            _item(
                "m9",
                "The test set was used for model selection or hyperparameter tuning.",
                "CLAIM 2020 #26",
                3,
                "yes",
                pass_if="no",
            ),
            _item("m10", "Missing data and how they were handled are described.", "CLAIM 2020 #13"),
        ],
    },
    {
        "key": "clinician",
        "name": "Clinician",
        "version": 1,
        "model": None,
        "perspective": (
            "You review clinical relevance: the population and setting, the intended use, whether the reference "
            "standard is the one used in practice, and how the model would fit into the clinical workflow."
        ),
        "items": [
            _item(
                "c1",
                "The clinical question or intended use (e.g. triage, diagnosis, prognosis) is stated.",
                "CLAIM 2020 #6",
                2,
            ),
            _item(
                "c2",
                "The study population and clinical setting match the intended use of the model.",
                "TRIPOD+AI 6",
                2,
            ),
            _item(
                "c3",
                "Demographic and clinical characteristics of the patients are reported for each data set.",
                "CLAIM 2020 #34",
                2,
            ),
            _item(
                "c4",
                "The reference standard is the one used in clinical practice for this question.",
                "CLAIM 2020 #15",
                2,
            ),
            _item(
                "c5", "The imaging acquisition (modality, scanner, protocol) is described.", "CLAIM 2020 #7"
            ),
            _item(
                "c6",
                "Performance is compared with clinicians or with the current standard of care.",
                "CLAIM 2020 #35",
                2,
            ),
            _item("c7", "Cases where the model failed are analysed.", "CLAIM 2020 #37"),
            _item("c8", "How the model would fit into the clinical workflow is discussed.", "CLAIM 2020 #39"),
            _item("c9", "Limitations, including bias and generalisability, are discussed.", "CLAIM 2020 #38"),
        ],
    },
    {
        "key": "statistician",
        "name": "Statistician",
        "version": 1,
        "model": None,
        "perspective": (
            "You review statistical analysis: performance metrics and their uncertainty, sample size, "
            "calibration, missing data, class imbalance and subgroup performance."
        ),
        "items": [
            _item(
                "s1", "Performance metrics are reported with confidence intervals.", "CLAIM 2020 #36", 3, "no"
            ),
            _item("s2", "The sample size is justified.", "TRIPOD+AI 10", 2),
            _item(
                "s3", "The number of patients and images in each data set is reported.", "CLAIM 2020 #33", 2
            ),
            _item("s4", "Calibration of predicted probabilities is assessed.", "TRIPOD+AI 23a", 2),
            _item("s5", "Missing data are quantified and the handling method is stated.", "TRIPOD+AI 11"),
            _item(
                "s6",
                "Performance is reported for relevant subgroups (e.g. sex, age, scanner, site).",
                "TRIPOD+AI 23b",
                2,
            ),
            _item(
                "s7", "The statistical tests used to compare models or readers are named.", "CLAIM 2020 #29"
            ),
            _item("s8", "Class imbalance is reported and addressed.", "TRIPOD+AI 13"),
            _item(
                "s9",
                "The operating threshold was chosen without using the test set.",
                "CLAIM 2020 #26",
                2,
                "no",
            ),
            _item("s10", "Robustness or sensitivity analyses are reported.", "CLAIM 2020 #30"),
        ],
    },
)

DEFAULT_EDITOR = {
    "model": None,
    "instructions": (
        "Weigh the reviewers' reports against each other. Name the checklist items where they disagree and "
        "give the final verdict with a reason grounded in their quotes."
    ),
}

DEFAULT_FULLTEXT = {"sources": ["pmc_oa", "unpaywall", "upload"], "contact": None, "max_chars": 60000}


def default_panel():
    return copy.deepcopy(list(DEFAULT_PANEL))


def default_review(contact=None):
    """A valid review.json dict with the default panel. Unpaywall needs a contact email, so it is left out
    when none is given."""
    fulltext = {**DEFAULT_FULLTEXT, "contact": contact}
    if not contact:
        fulltext["sources"] = [s for s in fulltext["sources"] if s != "unpaywall"]
    return {"schema": 1, "panel": default_panel(), "editor": dict(DEFAULT_EDITOR), "fulltext": fulltext}
