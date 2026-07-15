import math

import pytest

import material_catalog
import thermal_math


def _approved_tabulated(points):
    record = material_catalog.create_tabulated_material(
        name="Linear in log space",
        points=points,
        source={"title": "Test source", "url": "https://example.org/data"},
    )
    record["review_status"] = "approved"
    return record


def test_existing_default_calculation_is_unchanged():
    materials = ["CuOFHC", "PTFE", "SS304"]
    stages = [(4, 50, 320)]
    curves = thermal_math.buildCurves(materials, stages)
    areas = thermal_math.getAreas([0.29, 0.94, 1.19])
    total, individual = thermal_math.getThermalLoad(curves, areas, stages, 1)
    assert total == pytest.approx(0.06726750277124306)
    assert sum(individual) == pytest.approx(total)


def test_loglog_interpolation_matches_power_law_and_integrates():
    candidate = _approved_tabulated([[1, 1], [10, 100], [100, 10_000]])
    material_id = candidate["material_id"]
    catalog = thermal_math.getCatalog({material_id: candidate})
    curve = thermal_math.buildCurves([material_id], [(1, 100, 1)], catalog)[0]
    assert curve(math.sqrt(10)) == pytest.approx(10, rel=1e-9)


def test_tabulated_data_cannot_extrapolate():
    candidate = _approved_tabulated([[4, 1], [20, 2]])
    material_id = candidate["material_id"]
    catalog = thermal_math.getCatalog({material_id: candidate})
    with pytest.raises(ValueError, match="cannot be extrapolated"):
        thermal_math.buildCurves([material_id], [(1, 20, 1)], catalog)
