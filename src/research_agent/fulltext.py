"""Full text for the review panel: PMC Open Access (Europe PMC), Unpaywall (legal OA PDFs) and uploaded PDFs.

Never fatal: any failure falls back to the abstract and records why. Only open-access or user-provided
text is ever sent to a model provider."""

import hashlib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .connectors import SourceUnavailable, digest, fetch

MAX_PDF_BYTES = 30 * 1024 * 1024
MIN_PDF_TEXT = 100  # fewer extractable characters: a scanned or empty PDF


@dataclass(frozen=True)
class Section:
    title: str
    text: str


class FulltextUnavailable(Exception):
    """This source cannot give text for this paper; `reason` is short and safe to record."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


KINDS = (
    ("references", r"reference|bibliograph"),
    ("methods", r"method|material|patients and|study design|study population"),
    ("results", r"result"),
    ("abstract", r"abstract|summary"),
    ("discussion", r"discussion|conclusion|limitation"),
    ("introduction", r"introduction|background"),
)
PRIORITY = {"methods": 0, "results": 1, "abstract": 2, "introduction": 3, "discussion": 3, "other": 4}


def section_kind(title):
    for kind, pattern in KINDS:
        if re.search(pattern, title, re.IGNORECASE):
            return kind
    return "other"


def _render(section):
    return f"## {section.title}\n\n{section.text}" if section.title else section.text


def assemble(sections, max_chars):
    """Keep sections by priority (methods, results first) within max_chars, in document order.
    Returns (content, kept section titles, truncated)."""
    sections = [s for s in sections if s.text.strip() and section_kind(s.title) != "references"]
    order = sorted(range(len(sections)), key=lambda i: (PRIORITY[section_kind(sections[i].title)], i))
    budget, chosen, truncated = max_chars, {}, False
    for i in order:
        block = _render(sections[i])
        cost = len(block) + (2 if chosen else 0)
        if cost <= budget:
            chosen[i], budget = block, budget - cost
            continue
        truncated = True
        if budget > 200:
            chosen[i] = block[: budget - (2 if chosen else 0)]
            budget = 0
    kept = sorted(chosen)
    return "\n\n".join(chosen[i] for i in kept), [sections[i].title for i in kept], truncated


def _text(element):
    parts = []
    for node in element.iter():
        if node is element or node.tag not in ("p", "title"):
            continue
        if node.tag == "title" and node in list(element):
            continue  # the section's own title is the Section title
        parts.append(" ".join("".join(node.itertext()).split()))
    return "\n".join(p for p in parts if p)


def parse_jats(xml_text):
    """Europe PMC fullTextXML (JATS): front abstract plus each top-level body section; back matter
    (references) is never read. expat refuses entity-expansion attacks."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        raise FulltextUnavailable("unreadable XML") from None
    body = root.find("body")
    if body is None:
        raise FulltextUnavailable("no body in the XML")
    sections = []
    abstract = root.find("front/article-meta/abstract")
    if abstract is not None:
        sections.append(Section("Abstract", _text(abstract)))
    loose = [" ".join("".join(p.itertext()).split()) for p in body.findall("p")]
    if any(loose):
        sections.append(Section("", "\n".join(p for p in loose if p)))
    for sec in body.findall("sec"):
        sections.append(Section(" ".join((sec.findtext("title") or "").split()), _text(sec)))
    return sections


HEADING = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\.?\s+)?(abstract|introduction|background|materials and methods|patients and methods|"
    r"methods|methodology|results|discussion|conclusions?|limitations|references|bibliography)\s*:?\s*$",
    re.IGNORECASE,
)


def split_sections(text):
    sections, title, lines = [], "", []
    for line in text.splitlines():
        match = HEADING.match(line)
        if match:
            sections.append(Section(title, "\n".join(lines)))
            title, lines = match.group(1).strip().capitalize(), []
        elif line.strip():
            lines.append(" ".join(line.split()))
    sections.append(Section(title, "\n".join(lines)))
    return [s for s in sections if s.text]


def pdf_sections(data):
    if not data.startswith(b"%PDF-"):
        raise FulltextUnavailable("not a PDF")
    if len(data) > MAX_PDF_BYTES:
        raise FulltextUnavailable("PDF larger than 30 MB")
    try:
        from pypdf import PdfReader
    except ImportError:
        raise FulltextUnavailable("pypdf is not installed") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise FulltextUnavailable("encrypted PDF")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except FulltextUnavailable:
        raise
    except Exception:  # noqa: BLE001 -- pypdf raises many types for malformed files; all mean "unreadable"
        raise FulltextUnavailable("PDF could not be read") from None
    if len("".join(text.split())) < MIN_PDF_TEXT:
        raise FulltextUnavailable("no extractable text (scanned PDF?)")
    return split_sections(text)


def upload_name(paper_id):
    """File name of a paper's uploaded PDF: <run>/uploads/<name> (and in any extra upload directory)."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", paper_id) + ".pdf"


FULLTEXT_VERSION = "ft-1"
PMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"


def _pdf_bytes(response):
    data = response.content
    if not data.startswith(b"%PDF-") or len(data) > MAX_PDF_BYTES:
        raise ValueError("not an acceptable PDF")  # fetch() turns this into SourceUnavailable
    return data


class FullText:
    """Resolve the text a paper is reviewed on, in `spec["sources"]` order, else the abstract."""

    def __init__(self, store, spec, *, mode="live", uploads=(), client=None):
        self.store, self.spec, self.mode, self.client = store, spec, mode, client
        self.uploads = [Path(u) for u in uploads]

    def resolve(self, paper):
        reasons = []
        for source in self.spec["sources"]:
            try:
                sections, origin = getattr(self, f"_{source}")(paper)
            except FulltextUnavailable as exc:
                reasons.append(f"{source}: {exc.reason}")
                continue
            content, kept, truncated = assemble(sections, self.spec["max_chars"])
            if not content.strip():
                reasons.append(f"{source}: no text")
                continue
            return {
                "text_source": source,
                "content": content,
                "sections": kept,
                "truncated": truncated,
                "origin": origin,
                "reason": "; ".join(reasons) or None,
            }
        return {
            "text_source": "abstract",
            "content": paper["abstract"],
            "sections": [],
            "truncated": False,
            "origin": None,
            "reason": "; ".join(reasons) or "no full-text source configured",
        }

    def _cached(self, source, locator, load):
        """Successful extractions are cached (Raw Layer); failures are not, so a resume retries them."""
        key = digest({"version": FULLTEXT_VERSION, "source": source, "locator": locator})
        hit = self.store.cached_fulltext(key)
        if hit is None:
            sections, origin = load()
            hit = {"sections": [[s.title, s.text] for s in sections], "origin": origin}
            self.store.record_fulltext(key, source, locator, hit)
        return [Section(t, x) for t, x in hit["sections"]], hit["origin"]

    def _network(self):
        if self.mode == "demo":
            raise FulltextUnavailable("not fetched in demo mode")

    def _pmc_oa(self, paper):
        pmcid = paper.get("pmcid") or ""
        if not pmcid:
            raise FulltextUnavailable("no PMCID")
        self._network()
        url = PMC_URL.format(pmcid=pmcid)

        def load():
            try:
                xml = fetch(self.client, url, None, "pmc_oa", lambda response: response.text)
            except SourceUnavailable:
                raise FulltextUnavailable("request failed") from None
            return parse_jats(xml), url

        return self._cached("pmc_oa", pmcid, load)

    def _unpaywall(self, paper):
        doi = paper.get("doi") or ""
        if not doi:
            raise FulltextUnavailable("no DOI")
        self._network()
        if not self.spec.get("contact"):
            raise FulltextUnavailable("no contact email")

        def load():
            try:
                record = fetch(
                    self.client,
                    UNPAYWALL_URL.format(doi=doi),
                    {"email": self.spec["contact"]},
                    "unpaywall",
                    lambda response: response.json(),
                )
            except SourceUnavailable:
                raise FulltextUnavailable("request failed") from None
            locations = sorted(record.get("oa_locations") or [], key=lambda loc: not loc.get("is_best"))
            urls = list(dict.fromkeys(loc["url_for_pdf"] for loc in locations if loc.get("url_for_pdf")))
            if not urls:
                raise FulltextUnavailable("no open-access PDF")
            for url in urls[:2]:
                try:
                    return pdf_sections(fetch(self.client, url, None, "unpaywall", _pdf_bytes)), url
                except (SourceUnavailable, FulltextUnavailable):
                    continue
            raise FulltextUnavailable("PDF download failed")

        return self._cached("unpaywall", doi, load)

    def _upload(self, paper):
        name = upload_name(paper["id"])
        for directory in self.uploads:
            path = directory / name
            if path.is_file():
                if path.stat().st_size > MAX_PDF_BYTES:
                    raise FulltextUnavailable("PDF larger than 30 MB")
                data = path.read_bytes()
                sha = hashlib.sha256(data).hexdigest()
                return self._cached(
                    "upload", sha, lambda data=data, sha=sha: (pdf_sections(data), f"upload:{sha}")
                )
        raise FulltextUnavailable("no uploaded PDF")
