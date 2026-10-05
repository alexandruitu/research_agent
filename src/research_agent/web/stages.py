"""Stage catalog for the System map. Status is computed from measurements, never written by hand."""

import re
from pathlib import Path

import yaml

PLACEHOLDER = re.compile(r"\{([a-z0-9_.]+)(?::([^}]*))?\}")


def load_catalog(path):
    return yaml.safe_load(Path(path).read_text())["stages"]


def lookup(data, dotted):
    node = data
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def format_headline(template, metrics):
    """Fill `{path}` / `{path:.2f}` placeholders; None when any value is missing."""
    missing = False

    def fill(match):
        nonlocal missing
        value = lookup(metrics, match.group(1))
        if value is None:
            missing = True
            return ""
        return format(value, match.group(2) or "")

    text = PLACEHOLDER.sub(fill, template)
    return None if missing else text


def merge_metrics(reports):
    """`reports` is newest first; each top-level key comes from the newest report that has it."""
    merged = {}
    for report in reports:
        for key, value in report.items():
            merged.setdefault(key, value)
    return merged


def evaluate_stages(catalog, metrics):
    result = []
    for entry in catalog:
        stage = {
            "id": entry["id"],
            "title": entry["title"],
            "summary": entry["summary"].strip(),
            "limits": entry.get("limits", ""),
            "data_link": entry.get("data_link"),
            "status": "unmeasured",
            "headline": None,
            "caveat": None,
        }
        if entry.get("kind") == "input":
            stage["status"] = "input"
        else:
            # The first measurement that exists wins (e.g. the panel's Fleiss kappa before the old A/B kappa).
            for source in [*entry.get("alternatives", []), entry]:
                if source.get("measured_by") and all(
                    lookup(metrics, p) is not None for p in source["measured_by"]
                ):
                    stage["status"] = "measured"
                    template = source.get("headline")
                    stage["headline"] = format_headline(template, metrics) if template else None
                    if source.get("caveat_when") and lookup(metrics, source["caveat_when"]):
                        stage["status"], stage["caveat"] = "caveat", source.get("caveat")
                    break
        result.append(stage)
    return result
