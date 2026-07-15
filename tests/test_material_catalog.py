import json

import pytest

import material_catalog


SOURCE = {"title": "Example measurements", "url": "https://example.org/paper"}


def test_builtin_catalog_is_backward_compatible():
    catalog = material_catalog.load_builtin_catalog()
    assert len(catalog) == 78
    assert catalog["PTFE"]["fit_type"] == "loglog"
    assert catalog["CuOFHC"]["rrr"] == 100


def test_tabulated_points_are_sorted_and_define_range():
    candidate = material_catalog.create_tabulated_material(
        name="Example",
        points=[
            {"temperature_K": 20, "conductivity_W_mK": 4},
            {"temperature_K": 2, "conductivity_W_mK": 1},
        ],
        source=SOURCE,
    )
    assert candidate["equation_range_K"] == [2.0, 20.0]
    assert candidate["points"][0]["temperature_K"] == 2.0
    assert candidate["review_status"] == "draft"


@pytest.mark.parametrize(
    "points",
    [
        [{"temperature_K": 1, "conductivity_W_mK": 1}],
        [
            {"temperature_K": 1, "conductivity_W_mK": 1},
            {"temperature_K": 1, "conductivity_W_mK": 2},
        ],
        [
            {"temperature_K": 1, "conductivity_W_mK": 1},
            {"temperature_K": 2, "conductivity_W_mK": -1},
        ],
    ],
)
def test_invalid_tabulated_points_are_rejected(points):
    with pytest.raises(material_catalog.CatalogError):
        material_catalog.create_tabulated_material(name="Bad", points=points, source=SOURCE)


def test_published_fit_uses_whitelist_and_coefficient_count():
    candidate = material_catalog.create_published_material(
        name="Power material",
        fit_type="powerlaw",
        coefficients=[0.5, 2],
        equation_range_K=[1, 10],
        source=SOURCE,
    )
    assert candidate["coefficients"] == [0.5, 2.0]
    with pytest.raises(material_catalog.CatalogError):
        material_catalog.create_published_material(
            name="Bad power material",
            fit_type="powerlaw",
            coefficients=[0.5],
            equation_range_K=[1, 10],
            source=SOURCE,
        )


def test_only_approved_records_merge_and_builtins_cannot_be_replaced():
    builtins = material_catalog.load_builtin_catalog()
    candidate = material_catalog.create_tabulated_material(
        name="Example",
        points=[[1, 1], [10, 10]],
        source=SOURCE,
    )
    assert candidate["material_id"] not in material_catalog.merge_catalog(builtins, {candidate["material_id"]: candidate})
    candidate["review_status"] = "approved"
    assert candidate["material_id"] in material_catalog.merge_catalog(builtins, {candidate["material_id"]: candidate})
    candidate["material_id"] = "PTFE"
    with pytest.raises(material_catalog.CatalogError):
        material_catalog.merge_catalog(builtins, {"PTFE": candidate})


def test_bundle_round_trip_returns_imports_to_draft():
    candidate = material_catalog.create_tabulated_material(
        name="Example",
        points=[[1, 1], [10, 10]],
        source=SOURCE,
    )
    candidate["review_status"] = "approved"
    bundle = material_catalog.export_bundle([candidate])
    assert json.loads(bundle)["schema_version"] == 1
    imported = material_catalog.import_bundle(bundle)
    assert imported[0]["review_status"] == "draft"


def test_unsafe_source_scheme_is_rejected():
    with pytest.raises(material_catalog.CatalogError):
        material_catalog.create_tabulated_material(
            name="Unsafe", points=[[1, 1], [2, 2]], source={"title": "Bad", "url": "javascript:alert(1)"}
        )
