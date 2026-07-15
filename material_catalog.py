"""Material catalog loading, validation, and portable session bundles."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlparse


CATALOG_PATH = Path(__file__).with_name("nist_thermal_conductivity.json")
BUNDLE_SCHEMA_VERSION = 1
BUILTIN_FIT_TYPES = {
    "polylog",
    "loglog",
    "powerlaw",
    "NIST-experf",
    "lowTextrapolate",
    "Chebyshev",
    "OFHC_RRR_Wc",
}
SUPPORTED_FIT_TYPES = BUILTIN_FIT_TYPES | {"tabulated_loglog"}
FIT_COEFFICIENT_COUNTS = {
    "powerlaw": {2},
    "NIST-experf": {6},
    "OFHC_RRR_Wc": {21},
}


class CatalogError(ValueError):
    """Raised when a material record or bundle is unsafe or malformed."""


def load_builtin_catalog(path: Path = CATALOG_PATH) -> dict[str, dict[str, Any]]:
    """Load and validate the repository's built-in material records."""
    with path.open(encoding="utf-8") as handle:
        raw = json.load(handle)["materials"]
    return {material_id: validate_material(record, material_id, builtin=True) for material_id, record in raw.items()}


def _finite_positive(value: Any, field: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CatalogError(f"{field} must be a number.") from exc
    if not math.isfinite(result) or result <= 0:
        raise CatalogError(f"{field} must be finite and greater than zero.")
    return result


def normalize_points(points: Any) -> list[dict[str, float]]:
    """Return sorted, SI-normalized point records after strict validation."""
    if not isinstance(points, list) or len(points) < 2:
        raise CatalogError("Tabulated datasets require at least two points.")
    normalized = []
    for index, point in enumerate(points, start=1):
        if isinstance(point, dict):
            temperature = point.get("temperature_K")
            conductivity = point.get("conductivity_W_mK")
        elif isinstance(point, (list, tuple)) and len(point) == 2:
            temperature, conductivity = point
        else:
            raise CatalogError(f"Point {index} must contain temperature_K and conductivity_W_mK.")
        normalized.append(
            {
                "temperature_K": _finite_positive(temperature, f"Point {index} temperature"),
                "conductivity_W_mK": _finite_positive(conductivity, f"Point {index} conductivity"),
            }
        )
    normalized.sort(key=lambda item: item["temperature_K"])
    temperatures = [item["temperature_K"] for item in normalized]
    if len(set(temperatures)) != len(temperatures):
        raise CatalogError("Point temperatures must be unique.")
    return normalized


def validate_material(record: Any, material_id: str | None = None, *, builtin: bool = False) -> dict[str, Any]:
    """Validate a built-in or researched material without executing expressions."""
    if not isinstance(record, dict):
        raise CatalogError("A material record must be a JSON object.")
    result = deepcopy(record)
    name = str(result.get("name", "")).strip()
    if not name:
        raise CatalogError("Material name is required.")
    fit_type = str(result.get("fit_type", "")).strip()
    if fit_type not in SUPPORTED_FIT_TYPES:
        raise CatalogError(f"Unsupported fit type: {fit_type or '(missing)'}.")

    if fit_type == "tabulated_loglog":
        points = normalize_points(result.get("points"))
        result["points"] = points
        result.pop("coefficients", None)
        measured_range = [points[0]["temperature_K"], points[-1]["temperature_K"]]
        supplied_range = result.get("equation_range_K", measured_range)
        if [float(value) for value in supplied_range] != measured_range:
            raise CatalogError("A tabulated dataset range must match its first and last temperatures.")
        result["equation_range_K"] = measured_range
    else:
        coefficients = result.get("coefficients")
        if not isinstance(coefficients, list) or not coefficients:
            raise CatalogError("Published fits require a non-empty coefficient list.")
        try:
            coefficients = [float(value) for value in coefficients]
        except (TypeError, ValueError) as exc:
            raise CatalogError("Every fit coefficient must be numeric.") from exc
        if not all(math.isfinite(value) for value in coefficients):
            raise CatalogError("Every fit coefficient must be finite.")
        allowed_counts = FIT_COEFFICIENT_COUNTS.get(fit_type)
        if allowed_counts and len(coefficients) not in allowed_counts:
            expected = ", ".join(str(value) for value in sorted(allowed_counts))
            raise CatalogError(f"{fit_type} requires {expected} coefficients.")
        if fit_type == "loglog" and (len(coefficients) < 3 or len(coefficients) % 2 == 0):
            raise CatalogError("loglog requires an odd coefficient count: equal low/high fits plus a transition temperature.")
        result["coefficients"] = coefficients

        valid_range = result.get("equation_range_K")
        if not isinstance(valid_range, list) or len(valid_range) != 2:
            raise CatalogError("equation_range_K must contain a lower and upper temperature.")
        low = _finite_positive(valid_range[0], "Lower range")
        high = _finite_positive(valid_range[1], "Upper range")
        if low >= high:
            raise CatalogError("The valid temperature range must increase.")
        result["equation_range_K"] = [low, high]

    if fit_type == "OFHC_RRR_Wc":
        result["rrr"] = _finite_positive(result.get("rrr"), "RRR")

    result["name"] = name
    result["fit_type"] = fit_type
    result["material_id"] = material_id or str(result.get("material_id", "")).strip()
    if not result["material_id"]:
        raise CatalogError("material_id is required.")

    if builtin:
        result.setdefault("review_status", "built_in")
        result.setdefault("source", {"title": "Built-in thermal conductivity catalog", "source_type": "curated"})
    else:
        source = result.get("source")
        if not isinstance(source, dict) or not (source.get("url") or source.get("doi") or source.get("title")):
            raise CatalogError("Researched datasets require a source title, DOI, or URL.")
        source_url = str(source.get("url", "")).strip()
        if source_url and urlparse(source_url).scheme not in {"http", "https"}:
            raise CatalogError("Source URLs must use HTTP or HTTPS.")
        result.setdefault("review_status", "draft")
        if result["review_status"] not in {"draft", "approved"}:
            raise CatalogError("review_status must be draft or approved.")
        result.setdefault("material_details", {})
        result.setdefault("extraction", {"method": "manual"})
    return result


def make_material_id(name: str, source: dict[str, Any], qualifier: str = "") -> str:
    """Create a stable, readable ID without colliding with built-in shorthands."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "material"
    identity = "|".join(
        [name.strip().lower(), qualifier.strip().lower(), str(source.get("doi") or source.get("url") or source.get("title", ""))]
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:10]
    return f"user:{slug}:{digest}"


def create_tabulated_material(
    *,
    name: str,
    points: list[dict[str, Any]],
    source: dict[str, Any],
    material_details: dict[str, str] | None = None,
    extraction_method: str = "manual",
    notes: str = "",
) -> dict[str, Any]:
    """Build a draft candidate from reviewed or extracted point data."""
    details = {key: value.strip() for key, value in (material_details or {}).items() if value and value.strip()}
    qualifier = "|".join(f"{key}={value}" for key, value in sorted(details.items()))
    material_id = make_material_id(name, source, qualifier)
    return validate_material(
        {
            "material_id": material_id,
            "name": name,
            "fit_type": "tabulated_loglog",
            "points": points,
            "source": source,
            "material_details": details,
            "extraction": {"method": extraction_method, "notes": notes},
            "review_status": "draft",
        }
    )


def create_published_material(
    *,
    name: str,
    fit_type: str,
    coefficients: list[float],
    equation_range_K: list[float],
    source: dict[str, Any],
    material_details: dict[str, str] | None = None,
    extraction_method: str = "manual",
    notes: str = "",
    rrr: float | None = None,
) -> dict[str, Any]:
    """Build a draft only for a whitelisted, explicitly published fit family."""
    if fit_type not in BUILTIN_FIT_TYPES:
        raise CatalogError("The published equation does not use a supported fit family.")
    details = {key: value.strip() for key, value in (material_details or {}).items() if value and value.strip()}
    qualifier = "|".join(f"{key}={value}" for key, value in sorted(details.items()))
    material_id = make_material_id(name, source, qualifier)
    record = {
        "material_id": material_id,
        "name": name,
        "fit_type": fit_type,
        "coefficients": coefficients,
        "equation_range_K": equation_range_K,
        "source": source,
        "material_details": details,
        "extraction": {"method": extraction_method, "notes": notes},
        "review_status": "draft",
    }
    if rrr is not None:
        record["rrr"] = rrr
    return validate_material(record)


def merge_catalog(
    builtins: dict[str, dict[str, Any]], session_materials: dict[str, dict[str, Any]] | None = None
) -> dict[str, dict[str, Any]]:
    """Merge approved session records without allowing built-in ID replacement."""
    merged = deepcopy(builtins)
    for material_id, record in (session_materials or {}).items():
        candidate = validate_material(record, material_id)
        if material_id in merged:
            raise CatalogError(f"Session material ID collides with built-in material: {material_id}")
        if candidate["review_status"] == "approved":
            merged[material_id] = candidate
    return merged


def display_label(material_id: str, record: dict[str, Any]) -> str:
    details = record.get("material_details", {})
    qualifier = next((details.get(key) for key in ("grade", "condition", "direction", "purity") if details.get(key)), "")
    source = record.get("source", {})
    source_name = "" if record.get("review_status") == "built_in" else source.get("year") or source.get("title", "")
    extras = ", ".join(str(value) for value in (qualifier, source_name) if value)
    return f"{record['name']} ({material_id})" + (f" — {extras}" if extras else "")


def export_bundle(records: list[dict[str, Any]]) -> str:
    payload = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "exported_on": date.today().isoformat(),
        "materials": records,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def import_bundle(contents: str | bytes) -> list[dict[str, Any]]:
    try:
        payload = json.loads(contents)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CatalogError("The uploaded file is not valid JSON.") from exc
    if payload.get("schema_version") != BUNDLE_SCHEMA_VERSION or not isinstance(payload.get("materials"), list):
        raise CatalogError(f"Expected a material bundle with schema_version {BUNDLE_SCHEMA_VERSION}.")
    imported = []
    for raw in payload["materials"]:
        record = deepcopy(raw)
        record["review_status"] = "draft"
        imported.append(validate_material(record, record.get("material_id")))
    return imported
