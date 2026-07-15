"""Free, deterministic-first discovery and extraction of conductivity data."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import quote, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx


USER_AGENT = "thermal-conductivity-integrator/1.0 (scholarly material research)"
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5


class ResearchError(RuntimeError):
    """A recoverable discovery, retrieval, or extraction failure."""


@dataclass(frozen=True)
class ResearchRequest:
    material: str
    low_temperature_K: float
    high_temperature_K: float
    grade: str = ""
    condition: str = ""
    purity: str = ""
    direction: str = ""
    form: str = ""
    notes: str = ""

    def query(self) -> str:
        qualifiers = [self.grade, self.condition, self.purity, self.direction, self.form]
        detail = " ".join(value.strip() for value in qualifiers if value.strip())
        return (
            f'"{self.material.strip()}" {detail} thermal conductivity '
            f"{self.low_temperature_K:g} K {self.high_temperature_K:g} K"
        ).strip()

    def material_details(self) -> dict[str, str]:
        return {
            key: value.strip()
            for key, value in asdict(self).items()
            if key in {"grade", "condition", "purity", "direction", "form"} and value.strip()
        }


def _year(message: dict[str, Any]) -> int | None:
    for key in ("published-print", "published-online", "issued", "created"):
        parts = message.get(key, {}).get("date-parts", [])
        if parts and parts[0]:
            return int(parts[0][0])
    return None


def search_crossref(request: ResearchRequest, email: str = "", limit: int = 8) -> list[dict[str, Any]]:
    params = {
        "query.bibliographic": request.query(),
        "rows": min(max(limit, 1), 20),
        "select": "DOI,title,author,published-print,published-online,issued,created,URL,publisher,type",
    }
    if email:
        params["mailto"] = email
    headers = {"User-Agent": f"{USER_AGENT} mailto:{email}" if email else USER_AGENT}
    try:
        response = httpx.get("https://api.crossref.org/works", params=params, headers=headers, timeout=15)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ResearchError(f"Crossref search failed: {exc}") from exc
    sources = []
    for item in response.json().get("message", {}).get("items", []):
        title = " ".join(item.get("title") or []).strip()
        if not title:
            continue
        authors = [
            " ".join(part for part in (author.get("given", ""), author.get("family", "")) if part).strip()
            for author in item.get("author", [])
        ]
        doi = item.get("DOI", "")
        sources.append(
            {
                "title": title,
                "authors": [author for author in authors if author],
                "year": _year(item),
                "doi": doi,
                "url": f"https://doi.org/{doi}" if doi else item.get("URL", ""),
                "publisher": item.get("publisher", ""),
                "source_type": "peer_reviewed" if item.get("type") == "journal-article" else "scholarly",
                "discovered_by": "Crossref",
            }
        )
    return sources


def search_openalex(request: ResearchRequest, api_key: str, limit: int = 8) -> list[dict[str, Any]]:
    if not api_key:
        return []
    params = {
        "search": request.query(),
        "per-page": min(max(limit, 1), 20),
        "api_key": api_key,
        "select": "id,doi,display_name,publication_year,authorships,primary_location,type",
    }
    try:
        response = httpx.get("https://api.openalex.org/works", params=params, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ResearchError(f"OpenAlex search failed: {exc}") from exc
    sources = []
    for item in response.json().get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        authors = [entry.get("author", {}).get("display_name", "") for entry in item.get("authorships", [])]
        doi_url = item.get("doi") or ""
        sources.append(
            {
                "title": item.get("display_name", ""),
                "authors": [author for author in authors if author],
                "year": item.get("publication_year"),
                "doi": doi_url.removeprefix("https://doi.org/"),
                "url": location.get("landing_page_url") or doi_url or item.get("id", ""),
                "publisher": source.get("display_name", ""),
                "source_type": "peer_reviewed" if item.get("type") == "article" else "scholarly",
                "is_open_access": bool(location.get("is_oa")),
                "pdf_url": location.get("pdf_url") or "",
                "discovered_by": "OpenAlex",
            }
        )
    return sources


def lookup_open_access(doi: str, email: str) -> dict[str, str]:
    if not doi or not email:
        return {}
    url = f"https://api.unpaywall.org/v2/{quote(doi, safe='') }"
    try:
        response = httpx.get(url, params={"email": email}, headers={"User-Agent": USER_AGENT}, timeout=15)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ResearchError(f"Unpaywall lookup failed: {exc}") from exc
    location = response.json().get("best_oa_location") or {}
    return {
        "url": location.get("url_for_landing_page") or "",
        "pdf_url": location.get("url_for_pdf") or "",
        "license": location.get("license") or "",
    }


def deduplicate_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for source in sources:
        key = (source.get("doi") or source.get("url") or source.get("title", "")).lower().strip()
        if not key:
            continue
        if key in merged:
            for field, value in source.items():
                if value and not merged[key].get(field):
                    merged[key][field] = value
        else:
            merged[key] = source.copy()
    ranked = list(merged.values())
    for source in ranked:
        source["reliability"] = source_reliability(source)
    return sorted(ranked, key=lambda item: item["reliability"][0], reverse=True)


def source_reliability(source: dict[str, Any]) -> tuple[int, str]:
    """Return a transparent presentation rank; it is never an approval decision."""
    hostname = (urlparse(source.get("url", "")).hostname or "").lower()
    if hostname.endswith(".gov") or hostname in {"nist.gov", "www.nist.gov", "trc.nist.gov"}:
        return 5, "Official/government"
    if source.get("source_type") == "peer_reviewed" and source.get("doi"):
        return 4, "Peer-reviewed metadata"
    if source.get("source_type") in {"peer_reviewed", "scholarly"}:
        return 3, "Scholarly metadata"
    if source.get("source_type") in {"user_supplied", "user_upload"}:
        return 2, "User supplied"
    return 1, "Web source"


def search_gemini_grounded(request: ResearchRequest, api_key: str, model: str = "gemini-2.5-flash") -> list[dict[str, Any]]:
    """Use the free Gemini tier as a secondary, citation-producing web search."""
    if not api_key:
        return []
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=(
                "Find reliable primary sources or official databases containing numerical thermal conductivity "
                f"data, tables, equations, or coefficients for: {request.query()}. Prefer open-access sources."
            ),
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())]),
        )
        chunks = response.candidates[0].grounding_metadata.grounding_chunks or []
    except Exception as exc:
        raise ResearchError(f"Gemini grounded search failed: {exc}") from exc
    sources = []
    for chunk in chunks:
        web = getattr(chunk, "web", None)
        if web and getattr(web, "uri", None):
            sources.append(
                {
                    "title": getattr(web, "title", "Web source") or "Web source",
                    "url": web.uri,
                    "source_type": "web",
                    "discovered_by": "Gemini grounded search",
                }
            )
    return sources


def search_sources(
    request: ResearchRequest,
    *,
    contact_email: str = "",
    openalex_api_key: str = "",
    gemini_api_key: str = "",
    include_gemini: bool = False,
    limit: int = 8,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Search free scholarly indexes, returning partial results and recoverable warnings."""
    results: list[dict[str, Any]] = []
    warnings: list[str] = []
    for searcher, kwargs in (
        (search_crossref, {"email": contact_email, "limit": limit}),
        (search_openalex, {"api_key": openalex_api_key, "limit": limit}),
        (search_gemini_grounded, {"api_key": gemini_api_key}) if include_gemini else (None, {}),
    ):
        if searcher is None:
            continue
        try:
            results.extend(searcher(request, **kwargs))
        except ResearchError as exc:
            warnings.append(str(exc))
    return deduplicate_sources(results), warnings


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ResearchError("Only public HTTP(S) URLs are supported.")
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
    except socket.gaierror as exc:
        raise ResearchError("The source hostname could not be resolved.") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ResearchError("Private, loopback, and link-local source addresses are blocked.")


def fetch_public_document(url: str) -> tuple[bytes, str, str]:
    """Fetch a bounded public document while revalidating every redirect."""
    current = url.strip()
    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/pdf,text/plain;q=0.9,*/*;q=0.1"}
    checked_origins: set[str] = set()
    with httpx.Client(follow_redirects=False, timeout=httpx.Timeout(20, connect=10), headers=headers) as client:
        for _ in range(MAX_REDIRECTS + 1):
            _validate_public_url(current)
            parsed = urlparse(current)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            if origin not in checked_origins:
                checked_origins.add(origin)
                try:
                    robots_response = client.get(f"{origin}/robots.txt")
                    if robots_response.status_code == 200 and len(robots_response.content) <= 1_000_000:
                        parser = RobotFileParser()
                        parser.set_url(f"{origin}/robots.txt")
                        parser.parse(robots_response.text.splitlines())
                        if not parser.can_fetch(USER_AGENT, current):
                            raise ResearchError("This source disallows automated retrieval in robots.txt.")
                except ResearchError:
                    raise
                except httpx.HTTPError:
                    pass
            try:
                with client.stream("GET", current) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise ResearchError("The source returned an empty redirect.")
                        current = urljoin(current, location)
                        continue
                    response.raise_for_status()
                    content_length = int(response.headers.get("content-length", 0) or 0)
                    if content_length > MAX_DOCUMENT_BYTES:
                        raise ResearchError("The source is larger than the 20 MB limit.")
                    chunks = []
                    size = 0
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > MAX_DOCUMENT_BYTES:
                            raise ResearchError("The source is larger than the 20 MB limit.")
                        chunks.append(chunk)
                    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                    return b"".join(chunks), content_type, str(response.url)
            except httpx.HTTPError as exc:
                raise ResearchError(f"Source retrieval failed: {exc}") from exc
    raise ResearchError("The source exceeded the redirect limit.")


def document_to_text(contents: bytes, content_type: str, filename: str = "") -> str:
    is_pdf = content_type == "application/pdf" or filename.lower().endswith(".pdf") or contents.startswith(b"%PDF")
    if is_pdf:
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(contents))
            pages = []
            for page_number, page in enumerate(reader.pages, start=1):
                pages.append(f"\n--- Page {page_number} ---\n{page.extract_text() or ''}")
            return "".join(pages)
        except Exception as exc:
            raise ResearchError(f"PDF text extraction failed: {exc}") from exc
    try:
        from trafilatura import extract

        text = extract(contents, include_tables=True, include_links=False)
    except Exception as exc:
        raise ResearchError(f"HTML extraction failed: {exc}") from exc
    if not text:
        text = contents.decode("utf-8", errors="replace") if content_type.startswith("text/") else ""
    if not text.strip():
        raise ResearchError("No readable text was found in this source.")
    return text


_NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
_ROW_RE = re.compile(rf"^\s*({_NUMBER})\s*(?:,|;|\t|\s{{2,}})\s*({_NUMBER})\s*$")


def extract_tabulated_points(text: str) -> tuple[list[dict[str, float]], str]:
    """Extract conservative two-column tables that have a conductivity header nearby."""
    lines = [line.strip() for line in text.splitlines()]
    groups: list[list[dict[str, float]]] = []
    current: list[dict[str, float]] = []
    header_seen = False
    temperature_scale, temperature_offset, conductivity_scale = 1.0, 0.0, 1.0
    for line in lines:
        lower = line.lower()
        if ("temperature" in lower or re.search(r"\btemp\b", lower)) and (
            "conductiv" in lower or "w/m" in lower or "w m" in lower
        ):
            header_seen = True
            current = []
            temperature_scale, temperature_offset, conductivity_scale = 1.0, 0.0, 1.0
            if "°c" in lower or "deg c" in lower or "celsius" in lower:
                temperature_offset = 273.15
            if "mw/(m" in lower or "mw/m" in lower or "mw m-1" in lower:
                conductivity_scale = 1e-3
            elif "mw/(cm" in lower or "mw/cm" in lower or "mw cm-1" in lower:
                conductivity_scale = 0.1
            elif "w/(cm" in lower or "w/cm" in lower or "w cm-1" in lower:
                conductivity_scale = 100.0
            continue
        match = _ROW_RE.match(line)
        if header_seen and match:
            temperature, conductivity = map(float, match.groups())
            temperature = temperature * temperature_scale + temperature_offset
            conductivity *= conductivity_scale
            if temperature > 0 and conductivity > 0:
                current.append({"temperature_K": temperature, "conductivity_W_mK": conductivity})
            continue
        if current:
            if len(current) >= 2:
                groups.append(current)
            current = []
            header_seen = False
    if len(current) >= 2:
        groups.append(current)
    if not groups:
        return [], "No unambiguous two-column temperature/conductivity table was detected."
    best = max(groups, key=len)
    return best, f"Deterministically extracted {len(best)} rows from a labeled two-column table; verify units and values."


def gemini_extract_data(
    text: str, api_key: str, model: str = "gemini-2.5-flash"
) -> tuple[list[dict[str, float]], dict[str, Any] | None, str]:
    """Ask Gemini for a cited draft only when deterministic extraction is insufficient."""
    if not api_key:
        raise ResearchError("Gemini assistance is not configured.")
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise ResearchError("The google-genai dependency is not installed.") from exc
    schema = {
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "temperature_K": {"type": "number"},
                        "conductivity_W_mK": {"type": "number"},
                        "locator": {"type": "string"},
                    },
                    "required": ["temperature_K", "conductivity_W_mK", "locator"],
                },
            },
            "notes": {"type": "string"},
            "published_fit": {
                "type": "object",
                "properties": {
                    "fit_type": {
                        "type": "string",
                        "enum": ["", "polylog", "loglog", "powerlaw", "NIST-experf", "lowTextrapolate", "Chebyshev", "OFHC_RRR_Wc"],
                    },
                    "coefficients": {"type": "array", "items": {"type": "number"}},
                    "equation_range_K": {"type": "array", "items": {"type": "number"}},
                    "rrr": {"type": "number"},
                    "locator": {"type": "string"},
                },
                "required": ["fit_type", "coefficients", "equation_range_K", "rrr", "locator"],
            },
        },
        "required": ["points", "published_fit", "notes"],
    }
    prompt = (
        "Extract only explicitly printed thermal-conductivity table values or a published fit from this excerpt. "
        "Convert temperature to kelvin and conductivity to W/(m K). Do not estimate values from graphs, "
        "do not interpolate, and return empty values when data or units are ambiguous. A published fit_type must "
        "match one of the named families; do not translate arbitrary equations into a family. Use rrr=0 when absent. "
        "Include the page/table/equation locator.\n\n"
        + text[:120_000]
    )
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema),
        )
        payload = json.loads(response.text)
    except Exception as exc:
        raise ResearchError(f"Gemini extraction failed: {exc}") from exc
    points = [
        {"temperature_K": item["temperature_K"], "conductivity_W_mK": item["conductivity_W_mK"]}
        for item in payload.get("points", [])
    ]
    locators = sorted({item.get("locator", "") for item in payload.get("points", []) if item.get("locator")})
    note = payload.get("notes", "")
    if locators:
        note = f"{note} Locators: {', '.join(locators)}".strip()
    fit = payload.get("published_fit") or None
    if fit and not fit.get("fit_type"):
        fit = None
    elif fit and fit.get("locator"):
        note = f"{note} Fit locator: {fit['locator']}".strip()
    return points, fit, note


def gemini_extract_points(text: str, api_key: str, model: str = "gemini-2.5-flash") -> tuple[list[dict[str, float]], str]:
    """Backward-compatible points-only wrapper."""
    points, _fit, note = gemini_extract_data(text, api_key, model)
    return points, note
