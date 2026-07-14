"""Thermal-conductivity fit functions.

Fit implementations authored by Henry Nachman; copied verbatim from the source
compilation's fit_types.py so the curve math matches the published coefficients.
Each function takes temperature T (scalar or array) and the material's fit
coefficients as *params, and returns conductivity k in W/m-K.
"""
import numpy as np
from scipy.special import erf


def Nppoly(T, *param):
    # k = T * polynomial(T)
    return T * np.polyval(param, T)


def polylog(T, *param):
    # k = 10 ** polynomial(log10(T))
    logk = np.polyval(param, np.log10(T))
    return 10**logk


def loglog_func(T, *param):
    # compound fit: Nppoly (low T) and polylog (high T) joined by an error function.
    # last param is the erf transition temperature.
    erf_multiplicity = 15
    erf_param = param[-1]
    low_fit = Nppoly(T, *param[: (np.size(param) - 1) // 2])
    hi_fit = polylog(T, *param[(np.size(param) - 1) // 2 : -1])

    erf_low = 0.5 * (1 - erf(erf_multiplicity * (np.log10(T / erf_param))))
    erf_hi = 0.5 * (1 + erf(erf_multiplicity * (np.log10(T / erf_param))))
    return hi_fit * erf_hi + low_fit * erf_low


def power_law(T, A, B):
    # k = A * T ** B
    return A * T ** B


def NIST_experf(T, a, b, c, d, e, f):
    # 6-parameter fit with exponential and error-function terms (NIST website).
    logT = np.log10(T)
    k_val = (a + b * logT) * ((1 - erf(2 * (logT - c))) / 2) + (
        d + e * (np.exp(-1 * logT / f))
    ) * ((1 + erf(2 * (logT - c))) / 2)
    return 10**k_val


def OFHC_RRR_Wc(T, RRR_list, *params):
    # Ray Radebaugh's OFHC copper fit; RRR supplied separately from the params.
    t = T
    RRR = RRR_list[0]

    def w_0(t, RRR, params):
        return params[0] / ((RRR - 1) * t)

    def w_c(t, params):
        return (
            params[9] * np.log(t / params[10]) * np.exp(-((np.log(t / params[11]) / params[12]) ** 2))
            + params[13] * np.log(t / params[14]) * np.exp(-((np.log(t / params[15]) / params[16]) ** 2))
            + params[17] * np.log(t / params[18]) * np.exp(-((np.log(t / params[19]) / params[20]) ** 2))
        )

    def w_i_with_w_c(t, params, w_c):
        q = params[1] * (t ** params[2])
        r = params[1] * params[3] * (t ** (params[2] + params[4])) * np.exp(-((params[5] / t) ** params[6]))
        return q / (1 + r) + w_c

    def w_i0(RRR, w_i, w_0):
        return (params[7] * ((RRR - 1) ** params[8]) * w_i * w_0) / (w_i + w_0)

    w0 = w_0(t, RRR, params)
    wc = w_c(t, params)
    wi = w_i_with_w_c(t, params, wc)
    wi0 = w_i0(RRR, wi, w0)
    return 1 / (w0 + wi + wi0)


def Chebyshev(T, *param):
    # Chebyshev series in ln(T) giving ln(k).
    logT = np.log(T)
    return np.exp(np.polynomial.chebyshev.chebval(logT, param))


def lowTextrapolate(T, *params):
    # polylog above params[0]; power law between params[0] and params[1]; sentinel below.
    k = []
    if np.size(T) == 1:
        k_plus = 0
        if T > params[0]:
            logtemp = np.log10(T)
            for n in range(1, len(params)):
                k_plus += params[n - 1] * logtemp ** (n - 1)
            k = np.append(k, 10 ** (k_plus))
        elif T > params[1]:
            k = np.append(k, params[3] * T ** params[2])
        else:
            k = np.append(k, -1 * T)
        return float(k[0])  # k is a size-1 array; numpy 2.x rejects float() on non-0-d arrays
    for i in range(len(T)):
        k_plus = 0
        if T[i] > params[0]:
            logtemp = np.log10(T[i])
            for n in range(1, len(params)):
                k_plus += params[n - 1] * logtemp ** (n - 1)
            k = np.append(k, 10 ** (k_plus))
        elif T[i] > params[1]:
            k = np.append(k, params[3] * T[i] ** params[2])
        else:
            k = np.append(k, -1 * T[i])
    return k


# maps the compilation's fit_type strings to the functions above
FIT_DISPATCH = {
    "polylog": polylog,
    "loglog": loglog_func,
    "powerlaw": power_law,
    "NIST-experf": NIST_experf,
    "lowTextrapolate": lowTextrapolate,
    "Chebyshev": Chebyshev,
    "OFHC_RRR_Wc": OFHC_RRR_Wc,
}
