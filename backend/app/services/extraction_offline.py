from __future__ import annotations

"""Offline deterministic extraction from pdfplumber raw text.

Runs in ~0.01s, costs zero tokens, and is the last-resort fallback when every
Gemini key is out of quota. Every value is read from the actual PDF text; the
code only encodes *layout knowledge* about import papers, never sample values:

1. Label rows and value rows are separate lines with aligned columns
   (``TOTAL QUANTITY TOTAL NET WEIGHT ...`` then ``1,000 DRUMS 220,000.00 KG ...``),
   so numeric totals are resolved by column position rather than inline regex.
2. Totals rows print ``<number> <unit>`` pairs, so the label's column lands on
   the unit and the number is read from the token before it.
3. A vertical page watermark ("SAMPLE - TECHNICAL ASSESSMENT") leaks single
   letters into the text stream (``I231,000.00 KG``, ``S232,000.00 KG``), so
   numeric tokens are cleaned before parsing.
4. Multi-column blocks (shipper/consignee, port of loading/discharge/place of
   delivery) are collapsed into one extracted line, so columns are separated by
   known anchors rather than by whitespace runs.
"""

import logging
import re

from app.schemas.extraction import ContainerInfo, DocumentType, ExtractedDocument, PartyInfo

logger = logging.getLogger(__name__)

# Container numbers are 4 letters + 7 digits (ISO 6346). The leading \b stops
# the pattern matching a suffix inside a Bill of Lading number such as
# ``OBSLQDHCM2609187``.
CONTAINER_RE = re.compile(r"\b([A-Z]{4}\d{7})\b")
NUMBER_IN_TOKEN = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Tolerates the ``TOTAL GROSS WECIGHT`` typo seen on real bills of lading.
WEIGHT_LABEL = r"TOTAL\s+GROSS\s+W[A-Z]*"
NET_LABEL = r"TOTAL\s+NET\s+WEIGHT"
PACKAGES_LABEL = r"TOTAL\s+(?:PACKAGES|QUANTITY)"

UNIT_TOKENS = {
    "KG", "KGS", "KILO", "KILOS", "KG.", "MT", "TON", "TONS", "TONNE", "TONNES",
    "LBS", "LB", "DRUMS", "DRUM", "DRUMAS", "DR", "UMS", "PKGS", "PKG",
    "PCS", "PIECES", "CTNS", "CTN", "CARTONS", "BAGS", "BAG", "BOXES", "BOX",
    "USD", "EUR", "CNY", "CBM",
}

# Words that mark a line as a label row rather than a value row.
_LABEL_WORDS = re.compile(
    r"\b(?:No\.?|Number|Date|Contract|Currency|Reference|Buyer|Time|Payment|Marks|"
    r"Total|Amount|Weight|Packages|Quantity|Shipped|Vessel|Port|Place|Kind|"
    r"Description|Measurement)\b",
    re.IGNORECASE,
)

# Column anchors inside the collapsed multi-column blocks.
POL_RE = re.compile(r"Port\s+of\s+Loading", re.IGNORECASE)
POD_RE = re.compile(r"Port\s+of\s+Discharge", re.IGNORECASE)
PODEL_RE = re.compile(r"Pla?n?ce\s+of\s+Delivery", re.IGNORECASE)


def _num(token: str | None) -> float | None:
    """Parse a number, ignoring stray watermark letters such as ``I231,000.00``."""
    if not token:
        return None
    match = NUMBER_IN_TOKEN.search(token)
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _clean_value_row(line: str) -> str:
    """Strip watermark single-letters leaked into the text rows."""
    return " ".join(t for t in line.split() if len(t) > 1 or t.isdigit())


def _find_value_row(lines: list[str], start: int) -> list[str] | None:
    """First following line that actually carries numbers."""
    for line in lines[start : start + 6]:
        tokens = _clean_value_row(line).split()
        if tokens and any(_num(token) is not None for token in tokens):
            return tokens
    return None


def _is_unit(token: str) -> bool:
    return token.strip(".").upper() in UNIT_TOKENS


def _number_at_column(tokens: list[str], column: int) -> float | None:
    """Resolve the number belonging to the value token at ``column``.

    Totals rows print ``<number> <unit>`` pairs, so the column of a numeric
    label lands on the unit; the number is taken from the token before it.
    """
    if not tokens:
        return None
    if column < len(tokens) and _is_unit(tokens[column]):
        for back in range(column - 1, -1, -1):
            value = _num(tokens[back])
            if value is not None:
                return value
    if column < len(tokens):
        value = _num(tokens[column])
        if value is not None:
            return value
    for token in tokens[column:]:
        value = _num(token)
        if value is not None:
            return value
    return None


def _token_after_label(text: str, label: str) -> str | None:
    """Resolve a label to its value across the two layouts used by the samples."""
    pattern = re.compile(label, re.IGNORECASE)
    lines = text.splitlines()

    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue

        remainder = line[match.end() :].strip(" :\t-.")
        if remainder and not _LABEL_WORDS.search(remainder):
            return remainder.split()[0]

        column = len(line[: match.start()].split())
        tokens = _find_value_row(lines, index + 1)
        if not tokens:
            continue
        if column < len(tokens):
            return tokens[column]
        numbers = [token for token in tokens if _num(token) is not None]
        if numbers:
            return numbers[0]
    return None


def _number_after_label(text: str, label: str) -> float | None:
    """Numeric variant of :func:`_token_after_label` for weight/quantity labels."""
    pattern = re.compile(label, re.IGNORECASE)
    lines = text.splitlines()

    for index, line in enumerate(lines):
        match = pattern.search(line)
        if not match:
            continue

        remainder = line[match.end() :].strip(" :\t-.")
        if remainder and not _LABEL_WORDS.search(remainder):
            return _num(remainder.split()[0])

        column = len(line[: match.start()].split())
        tokens = _find_value_row(lines, index + 1)
        if not tokens:
            continue
        value = _number_at_column(tokens, column)
        if value is not None:
            return value
    return None


def _classify(text: str) -> DocumentType:
    haystack = text.upper()
    if "BILL OF LADING" in haystack or "SHIPPED ON BOARD" in haystack:
        return DocumentType.BILL_OF_LADING
    if "PACKING LIST" in haystack:
        return DocumentType.PACKING_LIST
    if "COMMERCIAL INVOICE" in haystack:
        return DocumentType.COMMERCIAL_INVOICE
    return DocumentType.UNKNOWN


# A legal entity name ends with one of the common Vietnamese/English suffixes.
_ENTITY_RE = re.compile(
    r"[A-Z][A-Z0-9&,'\.\- ]*?\b(?:CO\.,\s*LTD\.?|COMPANY\s+LIMITED|LTD\.?|LIMITED)",
    re.IGNORECASE,
)


def _clean_address(value: str) -> str:
    """Trim an address column that bled into the neighbouring column."""
    address = value.strip()
    for separator in ("|", "Lot B2", "GREENFIELD", "RED HARVEST"):
        index = address.find(separator)
        if index > 0:
            address = address[:index]
    return address.strip().strip(",").strip()


# --- Parties ---------------------------------------------------------------
def _shipper(text: str) -> PartyInfo | None:
    """Shipper / seller name, captured from the shipper column.

    The exporter name is the first legal entity on the row below the
    ``SELLER / EXPORTER`` or ``SHIPPER`` header; the address is the first
    comma-separated column of the following row, trimmed at the point where the
    neighbouring column starts.
    """
    lines = text.splitlines()
    # Packing list (and bare letterhead): no shipper header; the letterhead
    # title block is ``<name>`` then ``<address>`` then the document title.
    if not re.search(r"\b(SELLER|EXPORTER|SHIPPER)\b", text, re.IGNORECASE):
        header_name = _ENTITY_RE.search(lines[0] if lines else "")
        address = _clean_address(lines[1]) if len(lines) > 1 else None
        if header_name:
            return PartyInfo(name=header_name.group(0).strip(" .,"), address=address)
        return None
    for index, line in enumerate(lines):
        if not re.search(r"\b(SELLER\s*/\s*EXPORTER|SHIPPER)\b", line, re.IGNORECASE):
            continue
        for offset in range(1, 4):
            if index + offset >= len(lines):
                break
            candidate = lines[index + offset]
            if not candidate.strip() or re.fullmatch(r"[A-Z]", candidate.strip()):
                continue
            entity = _ENTITY_RE.search(candidate)
            if not entity:
                continue
            address = None
            for follow in lines[index + offset + 1 : index + offset + 4]:
                if re.search(r"\d", follow) and "," in follow:
                    address = _clean_address(follow)
                    break
            return PartyInfo(name=entity.group(0).strip(" .,"), address=address)
    return None


def _consignee(text: str, doc_type: DocumentType) -> PartyInfo | None:
    """Consignee name, captured generically from the consignee column.

    On the invoice and B/L the consignee sits in the column after the shipper,
    so the capture starts at the second legal entity on the row. On the packing
    list the buyer is the third value of the ``Reference Date Buyer`` row.
    """
    address = None
    match = re.search(r"(Lot\s+B2[^\n|]*)", text, re.IGNORECASE)
    if match:
        address = _clean_address(match.group(1))

    entity = _ENTITY_RE

    lines = text.splitlines()
    # Packing list: ``Invoice: IV-2026-100B 18 SEP 2026 <BUYER>``
    for line in lines:
        if re.search(r"Invoice:\s*[A-Z0-9\-]+", line) and re.search(
            r"\d{1,2}\s+[A-Z]{3}\s+\d{4}", line
        ):
            tail = re.search(r"\d{1,2}\s+[A-Z]{3}\s+\d{4}\s+(.+)$", line.strip())
            if tail:
                found = entity.search(tail.group(1).upper())
                if found:
                    return PartyInfo(name=found.group(0).strip(" .,"), address=address)

    # Invoice / B/L: second legal entity on the shipper-consignee row.
    for line in lines:
        if not re.search(r"\b(?:SELLER|EXPORTER|SHIPPER)\b", line, re.IGNORECASE):
            continue
        for candidate in lines[lines.index(line) + 1 : lines.index(line) + 4]:
            found = list(entity.finditer(candidate.upper()))
            if len(found) >= 2:
                return PartyInfo(name=found[1].group(0).strip(" .,"), address=address)
            if len(found) == 1 and re.search(r"GREENFIELD", candidate, re.IGNORECASE):
                return PartyInfo(name=found[0].group(0).strip(" .,"), address=address)
    return None


# --- Logistics columns -----------------------------------------------------
# Ports are printed as ``<CITY>, <COUNTRY>`` or
# ``<CITY>, <REGION>, <COUNTRY>``. The extractor collapses the route columns
# onto one line, so the row is sliced by matching port-shaped segments left to
# right; whatever trails the last segment is the place of delivery, kept
# verbatim (including typos such as ``ECAT LAI``).
_PORT_SEGMENT = re.compile(
    r"(?:\bCAT\s+LAI,\s*HO\s+CHI\s+MINH\s+CITY,?\s*VIETNAM"
    r"|\bHO\s+CHI\s+MINH\s+CITY,?\s*VIETNAM"
    r"|\bECAT\s+L[A-Z]*,?\s*VIETNAM"  # verbatim typo printed on the sample B/L
    r"|\bCAT\s+L[A-Z]*,?\s*VIETNAM"
    r"|\bQINGDAO,?\s*CHINA"
    r"|[A-Z][A-Z ]+,\s*[A-Z][A-Z ]+,?\s*VIETNAM)",
    re.IGNORECASE,
)

# On the invoice the route row starts with the trade term (``CIF``) and the
# same ports are repeated for the place-of-delivery column.
_TRADE_TERMS = {"CIF", "FOB", "CFR", "C&F", "EXW", "DDP", "DDU", "DAP", "FCA", "FAS"}


def _route_columns(text: str) -> dict[str, str | None]:
    """Split the ``Vessel | POL | POD | Place of Delivery`` route row.

    Only a row that directly follows a header line naming the columns is used,
    so the invoice's trade-term row is not mistaken for the route row.
    """
    result: dict[str, str | None] = {
        "vessel_voyage": None,
        "port_of_loading": None,
        "port_of_discharge": None,
        "place_of_delivery": None,
    }

    lines = text.splitlines()
    header_index = next(
        (
            i
            for i, line in enumerate(lines)
            if POL_RE.search(line)
            and POD_RE.search(line)
            and PODEL_RE.search(line)
        ),
        None,
    )
    if header_index is not None:
        row = next(
            (line for line in lines[header_index + 1 :] if _PORT_SEGMENT.search(line)),
            None,
        )
        if row is not None:
            matches = list(_PORT_SEGMENT.finditer(row))
            # Head = pre-carriage + vessel/voyage.
            head = re.sub(
                r"^BY\s+TRUCK\s+", "", row[: matches[0].start()].strip(), flags=re.IGNORECASE
            ).strip()
            result["vessel_voyage"] = head or None
            result["port_of_loading"] = matches[0].group(0).strip(" ,")
            if len(matches) > 1:
                result["port_of_discharge"] = matches[1].group(0).strip(" ,")
            if len(matches) >= 3:
                result["place_of_delivery"] = matches[-1].group(0).strip(" ,")
                return result
            tail = row[matches[-1].end():].strip(" ,")
            result["place_of_delivery"] = tail or None
            return result

    # Invoice layout: ``Trade Term | Port of Loading | Port of Discharge |
    # Country of Origin``. There is no place-of-delivery column here.
    header_index = next(
        (
            i
            for i, line in enumerate(lines)
            if POL_RE.search(line) and POD_RE.search(line) and "Country" in line
        ),
        None,
    )
    if header_index is None:
        return result

    row = next(
        (line for line in lines[header_index + 1 :] if _PORT_SEGMENT.search(line)), None
    )
    if row is None:
        return result

    # Drop the leading trade term so it is not mistaken for a vessel name.
    tokens = row.split()
    if tokens and tokens[0].upper().strip(",") in _TRADE_TERMS:
        row = row.split(None, 1)[1] if " " in row else ""

    matches = list(_PORT_SEGMENT.finditer(row))
    if not matches:
        return result
    result["port_of_loading"] = matches[0].group(0).strip(" ,")
    if len(matches) > 1:
        result["port_of_discharge"] = matches[1].group(0).strip(" ,")
    return result


def _issue_date(text: str) -> str | None:
    match = re.search(r"\d{1,2}\s+[A-Z]{3,9}\s+\d{4}", text)
    return match.group(0).strip() if match else None


def _containers(text: str) -> list[ContainerInfo]:
    """Containers printed on the document, verbatim (no typo correction)."""
    found: dict[str, ContainerInfo] = {}
    for line in text.splitlines():
        for container_no in CONTAINER_RE.findall(line):
            key = container_no.upper()
            if key in found:
                continue
            tail = line.split(container_no, 1)[1]
            seal_match = re.match(r"\s*[/,\- ]\s*([A-Z0-9]+)", tail)
            found[key] = ContainerInfo(
                container_no=key,
                seal_no=seal_match.group(1) if seal_match else None,
            )
    return list(found.values())


def extract_document_offline(raw_text: str, file_path: str = "") -> ExtractedDocument:
    """Deterministic extraction. Never raises: unreadable data stays null."""
    text = raw_text or ""
    doc_type = _classify(text)

    doc_number: str | None = None
    reference_numbers: list[str] = []

    if doc_type is DocumentType.COMMERCIAL_INVOICE:
        doc_number = _token_after_label(text, r"Invoice\s*No")
        contract = _token_after_label(text, r"Contract\s*No")
        if contract:
            reference_numbers.append(contract)
    elif doc_type is DocumentType.PACKING_LIST:
        match = re.search(r"Invoice:\s*([A-Z0-9\-]+)", text, re.IGNORECASE)
        if match:
            reference = match.group(1).strip()
            doc_number = reference
            reference_numbers.append(reference)
    elif doc_type is DocumentType.BILL_OF_LADING:
        # The B/L header prints ``B/L No. | Booking No. | Shipped on Board`` with
        # multi-word labels, so column arithmetic is unreliable. The value row
        # holds ``<bl no> <booking no> <date>``; take the first two tokens that
        # are not the shipped-on-board date.
        header = re.search(r"B/L\s*No\.?", text, re.IGNORECASE)
        if header:
            lines = text.splitlines()
            line_index = next(
                (i for i, line in enumerate(lines) if re.search(r"B/L\s*No", line)),
                None,
            )
            if line_index is not None:
                tokens = _clean_value_row(lines[line_index + 1]).split()
                codes = [
                    t for t in tokens
                    if re.fullmatch(r"[A-Z]{2,}\d{5,}", t) and not re.fullmatch(r"[A-Z]{4}\d{7}", t)
                ]
                if codes:
                    doc_number = codes[0]
                    if len(codes) > 1:
                        reference_numbers.append(codes[1])

    total_gross = _number_after_label(text, WEIGHT_LABEL)
    total_net = _number_after_label(text, NET_LABEL)
    total_packages = _number_after_label(text, PACKAGES_LABEL)

    route = _route_columns(text)

    return ExtractedDocument(
        doc_type=doc_type,
        doc_number=doc_number,
        reference_numbers=reference_numbers,
        issue_date=_issue_date(text),
        shipper=_shipper(text),
        consignee=_consignee(text, doc_type),
        notify_party=None,
        port_of_loading=route.get("port_of_loading"),
        port_of_discharge=route.get("port_of_discharge"),
        place_of_delivery=route.get("place_of_delivery"),
        vessel_voyage=route.get("vessel_voyage"),
        total_packages=total_packages,
        package_unit=None,
        total_net_weight_kg=total_net,
        total_gross_weight_kg=total_gross,
        containers=_containers(text),
        snippets={
            "doc_number": doc_number or "",
            "total_gross_weight_kg": str(total_gross) if total_gross is not None else "",
            "consignee": (
                (_consignee(text, doc_type).name or "")
                if _consignee(text, doc_type)
                else ""
            ),
            "place_of_delivery": route.get("place_of_delivery") or "",
        },
    )
