# Thermal Conductivity Integrator

A web tool for estimating the conductive **heat load** carried between two
temperature stages (e.g. the plates of a dilution refrigerator or cryostat) by
the materials in a coaxial cable. It integrates each material's thermal
conductivity curve over the temperature span using the Fourier law of heat
conduction.

**Live app:** https://thermal-integrator.streamlit.app

---

## What it computes

For a cable modeled as a set of concentric cylindrical layers (inner conductor,
dielectric, outer shield, and any additional layers), the steady-state
conductive heat flow through one layer between a low stage temperature `T_low`
and a high stage temperature `T_high` is

```
Q_layer = (A / L) * ∫  k(T) dT     from T_low to T_high
```

where

- `k(T)` — thermal conductivity of the layer material (W/m·K), from a fitted curve,
- `A` — cross-sectional area of that layer (m²),
- `L` — cable length (m).

The total load is the sum over all layers, multiplied by the number of cables.
Conductivities are given in **W/m·K**, so the code converts the millimeter
geometry to meters internally; results are reported in **watts (W)**.

Layer areas are computed as annuli from the radii you enter:

- Layer 1 (innermost): `π · r₁²`
- Layer *i* > 1: `π · (rᵢ² − rᵢ₋₁²)`

Radii must therefore **increase** from the innermost layer outward.

---

## Using the app

The app now has two workspaces:

- **Calculate** uses the curated built-in catalog plus any material datasets you
  have reviewed and approved in the current browser session.
- **Find a material** searches free scholarly indexes, retrieves open documents
  or accepts a legally obtained upload, extracts tables deterministically, and
  can optionally use Gemini's free tier for grounded discovery or difficult
  table extraction. Every result remains a draft until you approve it.

Researched datasets keep their source, DOI/URL, specimen details, extraction
method, valid range, and raw points or published coefficients. Sources are kept
separate rather than merged. Point-only datasets use shape-preserving
interpolation in log-temperature/log-conductivity space and cannot extrapolate
beyond their measured range.

1. **Number of Layers** — choose how many concentric layers the cable has
   (default 3: inner conductor, dielectric, outer shield). Change this first;
   the material/radius inputs update to match.
2. For each layer, enter:
   - **Material** — the shorthand code for the layer material (see the table
     below, also shown at the bottom of the app). It must match a supported
     shorthand exactly.
   - **Radius (mm)** — the *outer* radius of that layer. Radii must strictly
     increase from the inner layer to the outer layer.
3. **Low / High Temperature Stage (K)** — the two stage temperatures the cable
   bridges. The tool integrates the conductivity between them.
4. **Length of Cable (mm)** — physical length of the cable run between the stages.
5. **Number of Cables** — total loads are scaled by this count.
6. **Plot options** — plot temperature and/or conductivity on a log scale.
7. Press **Calculate Thermal Load**.

### Output

- The heat load contributed by **each layer**, in watts.
- The **total** thermal load (sum of all layers × number of cables).
- A plot of each layer's conductivity curve `k(T)` across the stage range.
  Dashed vertical lines mark where a material is being used **outside its valid
  fit range** (see below).

### Extrapolation warnings

Every material has a temperature range over which its fit was determined. If the
stage range you request extends beyond a material's valid range, the plot draws
a dashed **"Extrapolation Limit"** line at the boundary. Values past that line
are extrapolations of the fit and should be treated with caution — the fit may
diverge from real behavior.

---

## How the code works

The project is a small Streamlit app backed by a fit-evaluation library.

| File | Role |
|------|------|
| `app.py` | Streamlit UI: collects inputs, validates them, calls the math, and renders results and plots. |
| `thermal_math.py` | Builds a conductivity function per material, computes layer areas, and integrates the Fourier-law heat load with `scipy.integrate.quad`. |
| `fit_functions.py` | The library of conductivity fit functions (one per fit type) plus a `fit_type → function` dispatch table. |
| `nist_thermal_conductivity.json` | The material database: each shorthand maps to its fit type, coefficients, and valid temperature range. |
| `material_shorthand.txt` | The shorthand → display-name → range table shown in the app. |
| `requirements.txt` | Python dependencies. |

### Flow

1. `app.py` reads the material shorthands and radii the user typed.
2. It validates that every shorthand exists and that radii strictly increase.
3. `thermal_math.buildCurves()` looks up each material in the JSON database,
   selects the matching function from `fit_functions.FIT_DISPATCH`, and returns
   a callable `k(T)` bound to that material's coefficients.
4. `thermal_math.getAreas()` converts the radii into per-layer cross-sectional areas.
5. `thermal_math.getThermalLoad()` integrates `k(T)` over `[T_low, T_high]` for
   each layer with `quad`, applies `A / L` and the cable count, and sums.

### Fit types

Conductivity curves come from several published fitting forms. The database
stores which form each material uses:

| Fit type | Form |
|----------|------|
| `polylog` | `k = 10^(polynomial in log₁₀T)` |
| `loglog` | Low-T polynomial and high-T `polylog` blended with an error function |
| `powerlaw` | `k = A·T^B` |
| `NIST-experf` | 6-parameter NIST form with exponential and error-function terms |
| `Chebyshev` | Chebyshev series in `ln T` giving `ln k` |
| `lowTextrapolate` | `polylog` above a threshold, power law below it |
| `OFHC_RRR_Wc` | Ray Radebaugh's OFHC-copper fit, parameterized by RRR |

**OFHC copper (`CuOFHC`)** additionally depends on a residual-resistivity ratio
(RRR). It is baked into the database at **RRR = 100**; change the `rrr` field of
the `CuOFHC` entry in `nist_thermal_conductivity.json` for other values.

Fit implementations are by Henry Nachman; the coefficients are drawn from NIST
cryogenic material property fits
(https://trc.nist.gov/cryogenics/materials/materialproperties.htm) and other
published compilations.

---

## Running locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

To enable the optional research services, copy
`.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and configure:

- `CONTACT_EMAIL` for the Crossref polite pool and Unpaywall.
- `OPENALEX_API_KEY` for OpenAlex's free daily allowance.
- `GEMINI_API_KEY` for optional free-tier grounded search and structured
  extraction. The app works without Gemini, and shows a disclosure because
  free-tier content may be used by Google to improve its products.

Approved researched materials are session-only. Download their JSON bundle if
you want to import them in a later session or submit them for inclusion in the
curated catalog.

Run the automated suite with:

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Supported materials

78 materials. Use the **shorthand** in the material input. The valid range is the
temperature span over which the fit is defined; using a material outside it
extrapolates.

| Shorthand | Material | Valid range (K) | Fit type |
|-----------|----------|-----------------|----------|
| `GraphiteAGOT` | AGOT nuclear graphite | 0.072 – 4.22 | loglog |
| `Al1100` | Aluminum 1100 | 4 – 300 | polylog |
| `Al1100H14` | Aluminum 1100H14 | 0.0932 – 3.09 | loglog |
| `Al1100O` | Aluminum 1100O | 0.0908 – 2.11 | loglog |
| `Al3003F` | Aluminum 3003F | 4 – 300 | polylog |
| `Al5083O` | Aluminum 5083O | 4 – 300 | polylog |
| `Al6061T6` | Aluminum 6061T6 | 4 – 300 | polylog |
| `Al6063T5` | Aluminum 6063T5 | 4 – 296 | polylog |
| `Balsa11` | Balsa wood (11 lb/ft³) | 88 – 300 | polylog |
| `Balsa6` | Balsa wood (6 lb/ft³) | 88 – 300 | polylog |
| `BeechFlat` | Beechwood (flatwise) | 92 – 300 | polylog |
| `BeechGrain` | Beechwood (grain direction) | 92 – 300 | polylog |
| `BeCu` | Beryllium Copper | 2 – 80 | polylog |
| `Brass` | Brass | 53.5 – 972 | powerlaw |
| `CFRP` | Carbon-fiber-reinforced polymer (CFRP) | 0.0764 – 4.84 | loglog |
| `CFRPClearwater` | CFRP, Clearwater Composites rod | 0.134 – 4.84 | Chebyshev |
| `CFRPDPP` | CFRP, DPP | 0.104 – 4.02 | loglog |
| `CFRPGraphlite` | CFRP, Graphlite rod | 0.309 – 4.01 | loglog |
| `Constantan` | Constantan | 0.088 – 1070 | polylog |
| `CuNi` | Copper-Nickel | 0.112 – 2.75 | loglog |
| `CuNiCoax` | Copper-nickel coax cable | 0.05 – 7 | polylog |
| `Corian` | Corian (mineral-filled acrylic) | 0.0583 – 298 | loglog |
| `G10FR4` | FR-4 fiberglass-epoxy laminate | 0.304 – 2.97 | polylog |
| `G10Normal` | G-10CR fiberglass-epoxy (normal direction) | 4 – 300 | polylog |
| `G10Warp` | G-10CR fiberglass-epoxy (warp direction) | 4 – 300 | polylog |
| `GFPHeWarp` | Glass fabric/polyester laminate (He, warp direction) | 38 – 300 | polylog |
| `GFPN2Normal` | Glass fabric/polyester laminate (N₂, normal direction) | 84 – 300 | polylog |
| `GFPN2Warp` | Glass fabric/polyester laminate (N₂, warp direction) | 80 – 300 | polylog |
| `GraphiteBrad` | Graphite, brad grade | 0.1 – 4.99 | lowTextrapolate |
| `GraphiteA` | Graphite, grade a | 0.06 – 4.22 | polylog |
| `GraphiteP` | Graphite, grade p | 0.06 – 4.22 | polylog |
| `Inconel718` | Inconel 718 | 6 – 275 | polylog |
| `Invar` | Invar (Fe-36% Ni) | 4 – 300 | polylog |
| `Kapton` | Kapton (polyimide film) | 0.536 – 307 | polylog |
| `Ketron` | Ketron (PEEK) | 0.3 – 2.85 | loglog |
| `Kevlar29` | Kevlar 29 | 5 – 40 | powerlaw |
| `Kevlar49` | Kevlar 49 fiber (aramid) | 0.1 – 291 | NIST-experf |
| `Pb` | Lead | 4 – 296 | polylog |
| `Macor` | Macor (machinable glass-ceramic) | 0.337 – 3.21 | polylog |
| `Manganin` | Manganin | 0.0103 – 1180 | loglog |
| `MapleOak` | Maple/oak wood | 0.034 – 1000 | powerlaw |
| `Mo` | Molybdenum | 2 – 373 | polylog |
| `Mylar` | Mylar (PET film) | 1 – 83 | polylog |
| `NbTi` | NbTi (niobium-titanium superconductor) | 0.115 – 19.7 | loglog |
| `NbTi119Coax` | NbTi coax (type 119) | 0.1 – 4 | polylog |
| `NbTi160Coax` | NbTi coax (type 160) | 0.1 – 4 | polylog |
| `Nichrome` | Nichrome | 4 – 300 | polylog |
| `FeNi2` | Nickel Steel Fe 2.25 Ni | 4 – 300 | polylog |
| `FeNi3` | Nickel Steel Fe 3.25 Ni | 4 – 300 | polylog |
| `FeNi5` | Nickel Steel Fe 5.0 Ni | 4 – 300 | polylog |
| `FeNi9` | Nickel Steel Fe 9.0 Ni | 4 – 300 | polylog |
| `Nylon` | Nylon | 4 – 300 | polylog |
| `CuOFHC` | OFHC copper (RRR = 100) | 0.2 – 1250 | OFHC_RRR_Wc |
| `PhosBronze` | Phosphor bronze | 3.22 – 448 | polylog |
| `Pt` | Platinum | 3 – 298 | polylog |
| `GraphitePOCO` | POCO AXM-5Q graphite | 0.063 – 3.25 | loglog |
| `PS2Freon` | Polystyrene foam (1.99 lb/ft³, Freon) | 90 – 300 | polylog |
| `PS2` | Polystyrene foam (2.0 lb/ft³) | 33 – 300 | polylog |
| `PS3` | Polystyrene foam (3.12 lb/ft³) | 7 – 300 | polylog |
| `PS6` | Polystyrene foam (6.24 lb/ft³) | 4 – 300 | polylog |
| `PU2Freon` | Polyurethane foam (1.99 lb/ft³, Freon) | 76 – 300 | polylog |
| `PU2CO2` | Polyurethane foam (2.0 lb/ft³, CO₂) | 100 – 300 | polylog |
| `PU3He` | Polyurethane foam (3.06 lb/ft³, He) | 30 – 300 | polylog |
| `PU4Freon` | Polyurethane foam (4.00 lb/ft³, Freon) | 88 – 300 | polylog |
| `PVCair` | PVC foam (1.25 lb/ft³, air) | 100 – 300 | polylog |
| `PVCCO2` | PVC foam (3.5 lb/ft³, CO₂) | 125 – 300 | polylog |
| `Si` | Silicon | 50 – 296 | powerlaw |
| `SS304` | Stainless Steel 304 | 0.385 – 1670 | loglog |
| `SS304L` | Stainless Steel 304L | 4 – 300 | polylog |
| `SS310` | Stainless Steel 310 | 0.374 – 1270 | loglog |
| `SS316` | Stainless Steel 316 | 4 – 300 | polylog |
| `SS321` | Stainless Steel 321 | 0.393 – 1620 | loglog |
| `Stycast` | Stycast (epoxy) | 0.0609 – 1.81 | powerlaw |
| `PTFE` | Teflon | 0.124 – 297 | loglog |
| `Ti6Al4V` | Ti-6Al-4V | 0.0566 – 1170 | loglog |
| `Ti15333` | Titanium 15-3-3-3 | 1.4 – 300 | polylog |
| `Torlon` | Torlon (PAI) | 0.303 – 2.98 | loglog |
| `Vespel` | Vespel (polyimide) | 0.0703 – 3.03 | loglog |
