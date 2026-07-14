import math
import json
from scipy.integrate import quad
import fit_functions

#### PROGRAM ####

_MATERIALS = json.load(open("nist_thermal_conductivity.json"))["materials"]


def _makeCurve(mat):
    """Return a scalar conductivity function k(T) for one material entry."""
    func = fit_functions.FIT_DISPATCH.get(mat["fit_type"])
    if func is None:
        raise ValueError(f"Unknown fit type: {mat['fit_type']}")
    coeffs = mat["coefficients"]
    # OFHC copper takes its RRR value separately from the coefficient list
    if mat["fit_type"] == "OFHC_RRR_Wc":
        rrr = mat["rrr"]
        return lambda t, func=func, coeffs=coeffs, rrr=rrr: float(func(t, [rrr], *coeffs))
    return lambda t, func=func, coeffs=coeffs: float(func(t, *coeffs))


def buildCurves(materials, heat_stages):
    try:
        mat_data = [_MATERIALS[m] for m in materials]
    except KeyError as e:
        raise ValueError(f"Invalid material type (use shorthand notation): {e}")

    curves = []
    for mat in mat_data:
        # warn if the requested stage range extends past the fit's valid range
        if mat["equation_range_K"][0] > heat_stages[0][0] or mat["equation_range_K"][1] < heat_stages[-1][1]:
            print(f"Extrapolation Warning: the heat stage range ({heat_stages[0][0]}-{heat_stages[-1][1]} K) is outside of {mat['name']} equation range ({mat['equation_range_K'][0]}-{mat['equation_range_K'][1]} K)")
        curves.append(_makeCurve(mat))
    return curves


def getRanges(materials):
    """Valid [Tlow, Thigh] fit range (K) for each material."""
    return [_MATERIALS[m]["equation_range_K"] for m in materials]


def getAreas(radii_mm):
    areas = []
    for i in range(len(radii_mm)):
        if i == 0:
            areas.append(math.pi * (radii_mm[i] ** 2))
        else:
            areas.append(math.pi * (radii_mm[i] ** 2 - radii_mm[i-1] ** 2))
    return areas


def getThermalLoad(curves, areas, heat_stages, n_cables):
    # sums the total thermal load for each material & stage using the Fourier law
    fluxes = [0] * len(curves)
    for stage in heat_stages:
        low, high, length = stage
        for i in range(len(curves)):
            heat_sum, *_ = quad(curves[i], low, high)
            fluxes[i] += n_cables * 1e-3 * heat_sum * areas[i] / length

    q = sum(fluxes)

    return q, fluxes
