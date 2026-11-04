"""Pure normalization helpers used for validation, deduplication and matching."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import urlsplit

# Common legal-form suffixes removed when comparing company names.
_LEGAL_SUFFIXES = {
    "sa",
    "sas",
    "sasu",
    "sarl",
    "eurl",
    "sca",
    "scs",
    "snc",
    "gmbh",
    "ag",
    "kg",
    "ug",
    "ltd",
    "limited",
    "llc",
    "llp",
    "inc",
    "incorporated",
    "corp",
    "corporation",
    "co",
    "company",
    "plc",
    "bv",
    "nv",
    "srl",
    "spa",
    "sl",
    "oy",
    "ab",
    "as",
    "aps",
    "sprl",
}

_DOMAIN_LABEL_RE = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")

# Country handling: ISO 3166-1 alpha-2 codes with common English/French names.
COUNTRIES: dict[str, str] = {
    "FR": "France",
    "BE": "Belgium",
    "CH": "Switzerland",
    "LU": "Luxembourg",
    "DE": "Germany",
    "AT": "Austria",
    "NL": "Netherlands",
    "ES": "Spain",
    "PT": "Portugal",
    "IT": "Italy",
    "GB": "United Kingdom",
    "IE": "Ireland",
    "DK": "Denmark",
    "SE": "Sweden",
    "NO": "Norway",
    "FI": "Finland",
    "PL": "Poland",
    "CZ": "Czechia",
    "RO": "Romania",
    "GR": "Greece",
    "US": "United States",
    "CA": "Canada",
    "MX": "Mexico",
    "BR": "Brazil",
    "MA": "Morocco",
    "TN": "Tunisia",
    "DZ": "Algeria",
    "SN": "Senegal",
    "CI": "Côte d'Ivoire",
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "QA": "Qatar",
    "EG": "Egypt",
    "IN": "India",
    "SG": "Singapore",
    "JP": "Japan",
    "AU": "Australia",
    "ZA": "South Africa",
}
_COUNTRY_ALIASES: dict[str, str] = {
    "uk": "GB",
    "great britain": "GB",
    "england": "GB",
    "usa": "US",
    "united states of america": "US",
    "allemagne": "DE",
    "belgique": "BE",
    "suisse": "CH",
    "espagne": "ES",
    "italie": "IT",
    "pays-bas": "NL",
    "royaume-uni": "GB",
    "etats-unis": "US",
    "maroc": "MA",
    "tunisie": "TN",
    "algerie": "DZ",
    "irlande": "IE",
    "autriche": "AT",
    "pologne": "PL",
    "suede": "SE",
    "cote d'ivoire": "CI",
    "ivory coast": "CI",
    "emirats arabes unis": "AE",
    "uae": "AE",
}

EMPLOYEE_RANGES: list[tuple[int, int | None, str]] = [
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 500, "201-500"),
    (501, 1000, "501-1000"),
    (1001, 5000, "1001-5000"),
    (5001, None, "5001+"),
]


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalize_company_name(name: str) -> str:
    """Return a comparison key: lower-case, no accents/punctuation/legal suffix.

    >>> normalize_company_name("Société Générale d'Équipement S.A.")
    'societe generale d equipement'
    """
    text = strip_accents(name).casefold()
    text = text.replace("&", " and ")
    text = re.sub(r"(?<=\b[a-z])\.(?=[a-z]\b)", "", text)  # S.A. -> SA
    text = re.sub(r"[^a-z0-9]+", " ", text)
    tokens = text.split()
    while tokens and tokens[-1] in _LEGAL_SUFFIXES and len(tokens) > 1:
        tokens.pop()
    return " ".join(tokens)


def normalize_domain(website: str | None) -> str | None:
    """Extract a normalized registrable host from a URL or bare domain.

    Returns ``None`` for empty input. Raises ``ValueError`` for invalid hosts.

    >>> normalize_domain("HTTPS://www.Example.COM:443/about?x=1")
    'example.com'
    """
    if website is None:
        return None
    raw = website.strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parts.scheme!r}")
    host = (parts.hostname or "").rstrip(".").lower()
    if parts.username or parts.password:
        raise ValueError("URLs containing credentials are not accepted")
    if host.startswith("www."):
        host = host[4:]
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"Invalid internationalized domain: {host!r}") from exc
    labels = host.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL_RE.match(label) for label in labels):
        raise ValueError(f"Invalid domain: {host!r}")
    if labels[-1].isdigit():
        raise ValueError("IP addresses are not accepted as company domains")
    return host


def normalize_website(website: str | None) -> str | None:
    """Return a canonical ``https://domain`` style URL, or None."""
    domain = normalize_domain(website)
    if domain is None:
        return None
    raw = website.strip() if website else ""
    scheme = "http" if raw.lower().startswith("http://") else "https"
    return f"{scheme}://{domain}"


def normalize_email(email: str | None) -> str | None:
    if email is None:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


def email_hash(email: str) -> str:
    """SHA-256 of a normalized e-mail. Used for suppression lists (data minimization)."""
    normalized = normalize_email(email) or ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def normalize_country(value: str | None) -> str | None:
    """Map a country code or common name to an ISO alpha-2 code.

    Raises ``ValueError`` if the value is not recognized.
    """
    if value is None:
        return None
    raw = collapse_whitespace(value)
    if not raw:
        return None
    upper = raw.upper()
    if upper in COUNTRIES:
        return upper
    key = strip_accents(raw).casefold()
    for code, name in COUNTRIES.items():
        if strip_accents(name).casefold() == key:
            return code
    if key in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[key]
    raise ValueError(f"Unknown country: {value!r}. Use an ISO code such as FR, DE, US.")


def country_name(code: str | None) -> str:
    if not code:
        return "—"
    return COUNTRIES.get(code, code)


def employee_range(count: int | None) -> str | None:
    if count is None:
        return None
    for low, high, label in EMPLOYEE_RANGES:
        if count >= low and (high is None or count <= high):
            return label
    return None


def name_similarity(a: str, b: str) -> float:
    """Similarity ratio (0..1) between two *normalized* company names."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def slugify(value: str) -> str:
    text = strip_accents(value).casefold()
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")
