"""A tiny, valid, text-bearing PDF built in memory (Helvetica, one page, one line per string)."""


def tiny_pdf(lines):
    def escape(text):
        return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    body = "BT /F1 10 Tf 12 TL 50 780 Td " + " ".join(f"({escape(line)}) Tj T*" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> "
            "/Contents 5 0 R >>"
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Length {len(body)} >>\nstream\n{body}\nendstream",
    ]
    out, offsets = "%PDF-1.4\n", []
    for number, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n"
    out += "".join(f"{offset:010d} 00000 n \n" for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return out.encode("latin-1")


PAPER_LINES = [
    "A synthetic test paper",
    "Methods",
    "Data were split at patient level into training and test sets.",
    "The reference standard was invasive fractional flow reserve.",
    "Results",
    "The AUC was 0.91 (95% CI 0.88-0.94) on the external test set.",
    "References",
    "1. A reference that must never reach a reviewer.",
]
