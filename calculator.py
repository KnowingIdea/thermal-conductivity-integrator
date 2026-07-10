import math
from scipy.integrate import quad
import json

#### CONFIG ####

# materials (uses shorthand in tc_lookup.py)
inner = "PhosCu"
dielectric = "PTFE"
outer = "SS304"

# geometry
#radii_mm = [0.287, 0.94, 1.19] # inner, dielectric, outer
# 047
radii_mm = [0.0635, 0.0635, 0.0635]

# number of cables between plates
n_cables = 16


#-300 250 -50 250 -1 500-0.01
#try: 50-4-mixing, 50-1-mixing, 300-4-mixing, 300-50-mixing

# 50K plate load: 0.021120781659567794 W
# 1K plate load
#4-1
# setup
heat_stages = [(1, 50, 500)] # {low temp (K), high temp (K), length (mm)} for each stage
# 4K - 300K

#### PROGRAM ####

# for each material: get the coefficients and correct equation from the json
try:
    data = json.load(open("nist_thermal_conductivity.json"))
    mat_data = (data["materials"][inner], data["materials"][dielectric], data["materials"][outer])
except KeyError:
    print("Invalid material type (use shorthand notation)")


# model function 1: polynomial of log10(T)
def log_polynomial(args, t):
    a, b, c, d, e, f, g, h, i = args
    x = math.log10(t)
    poly = a + b * x + c * x**2 + d * x**3 + e * x**4 + f * x**5 + g * x**6 + h * x**7 + i * x**8
    return math.pow(10, poly)

# model function 2: rational function of sqrt(T)
def rational_sqrt(args, t):
    a, b, c, d, e, f, g, h, i = args
    rat = (a + c * t**0.5 + e * t + g * t**1.5 + i * t**2) / (1 + b * t**0.5 + d * t + f * t**1.5 + h * t**2)
    return math.pow(10, rat)

curves = [] # functions that hold inner, dielectric, and outer conductivity curves

for mat in mat_data:
    # check that the equation data range is within the range of heat stages
    if mat["equation_range_K"][0] > heat_stages[0][0] or mat["equation_range_K"][1] < heat_stages[-1][1]:
        print(f"Extrapolation Warning: the heat stage range ({heat_stages[0][0]}-{heat_stages[-1][1]} K) is outside of {mat['name']} equation range ({mat['equation_range_K'][0]}-{mat['equation_range_K'][1]} K)")

    # creates the curve functions based on the coefficients for each material    
    if mat["equation_type"] == "log10_polynomial":
        curves.append(lambda t, mat=mat: log_polynomial(mat["coefficients"], t))
    elif mat["equation_type"] == "rational_sqrtT":
        curves.append(lambda t, mat=mat: rational_sqrt(mat["coefficients"], t))
    else:
        raise ValueError("Equation parsing error")

# calculates the area of each material based on radii
areas = [] 
for i in range(3):
    if i == 0:
        areas.append(math.pi * (radii_mm[i] ** 2))
    else:
        areas.append(math.pi * (radii_mm[i] ** 2 - radii_mm[i-1] ** 2))

# sums the total thermal load for each material & stage using the Fourier law
fluxes = [0, 0, 0]
for stage in heat_stages:
    low, high, length = stage
    for i in range(3):
        heat_sum, *_ = quad(curves[i], low, high)
        print((0.22 * (1 - 0.01)) * 1e-3 * areas[i] / length)
        fluxes[i] += 1e-3 * (heat_sum) * areas[i] / length
        #fluxes[i] += 1e-3 * (heat_sum + (0.22 * (1 - 0.01))) * areas[i] / length

# total thermal load
q = sum(fluxes) * n_cables

print(q)


print()