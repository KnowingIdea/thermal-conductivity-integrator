import streamlit as st
import thermal_math
import pandas as pd
import plotly.graph_objects as go
import numpy as np
import re

st.title("Thermal Conductivity Integrator")
st.write("This is a simple web tool to calculate the thermal load between " \
"cryogenic stages due to the thermal conductivity of materials used in the " \
"coaxial cables. The tool uses the Fourier law of heat conduction to integrate" \
" the thermal load over the temperature range of each stage, using the thermal " \
" conductivity equations provided by NIST at https://trc.nist.gov/cryogenics/materials/materialproperties.htm")

st.write("Please follow the shorthand notation for materials found in the table" \
" at the bottom of the page.")

# default (material, radius mm) per layer, extended for extra layers
LAYER_DEFAULTS = [("CuRRR100", 0.29), ("PTFE", 0.94), ("SS304", 1.19)]

# chosen outside the form so changing it reruns and renders the right inputs
n_layers = st.number_input("Number of Layers", min_value=1, value=3, step=1)

with st.form("input_form"):
    materials = []
    radii_mm = []
    for i in range(int(n_layers)):
        def_mat, def_radius = LAYER_DEFAULTS[i] if i < len(LAYER_DEFAULTS) else ("", 0.0)
        materials.append(st.text_input(f"Layer {i+1} Material", value=def_mat, key=f"mat_{i}"))
        radii_mm.append(st.number_input(f"Layer {i+1} Radius (mm)", value=def_radius, key=f"rad_{i}", format="%0.5f"))

    low_temp = st.number_input("Low Temperature Stage (K)", value=4.000)
    high_temp = st.number_input("High Temperature Stage (K)", value=50.000)
    length = st.number_input("Length of Cable (mm)", value=320.000)

    # n_intermediate_stages = st.number_input("Number of Intermediate Stages", value = 0, step = 1)

    n_cables = st.number_input("Number of Cables", value=1, step=1)
    
    log_temp_plot = st.checkbox("Plot Temperature Logarithmically?", value=True)
    log_conductivity_plot = st.checkbox("Plot Conductivity Logarithmically?", value=True)

    submitted = st.form_submit_button("Calculate Thermal Load")

df = pd.read_csv("material_shorthand.txt", sep=",", names = ["Shorthand", "Material", "Valid Temperature Range (K)"])
df = df[["Material", "Shorthand", "Valid Temperature Range (K)"]]

if submitted:
    # validate materials against the shorthand table (blank/unknown -> KeyError in backend)
    valid_shorthands = set(df["Shorthand"])
    bad = [f"Layer {i+1}: '{m}'" for i, m in enumerate(materials) if m not in valid_shorthands]
    if bad:
        st.error("Unknown material shorthand — see the table below. " + ", ".join(bad))
        st.stop()

    # areas assume radii increase outward; otherwise annulus areas go negative
    if any(radii_mm[i] <= radii_mm[i-1] for i in range(1, len(radii_mm))):
        st.error("Radii must strictly increase from inner to outer layer.")
        st.stop()

    heat_stages = [(low_temp, high_temp, length)]

    curves = thermal_math.buildCurves(materials, heat_stages)
    areas = thermal_math.getAreas(radii_mm)
    q, indiv_q = thermal_math.getThermalLoad(curves, areas, heat_stages, n_cables)

    for i, mat in enumerate(materials):
        st.write(f"Layer {i+1} ({mat}) Load: {indiv_q[i]:.4e} W")

    with st.container(border=True):
        st.write(f"Total Thermal Load: {q:.4e} W")

    t_values = np.linspace(low_temp, high_temp, 100)
    layer_curves = [np.array([c(t) for t in t_values]) for c in curves]

    # valid temperature range per layer, parsed from the shorthand table
    ranges = []
    for mat in materials:
        range_text = df.loc[df["Shorthand"] == mat, "Valid Temperature Range (K)"].values[0]
        ranges.append([int(x) for x in re.findall(r"\d+\.?\d*", range_text)])

    plotted_ranges = ranges
    if log_temp_plot:
        t_values = np.log10(t_values)
        plotted_ranges = [(np.log10(r[0]), np.log10(r[1])) for r in ranges]
    if log_conductivity_plot:
        layer_curves = [np.log10(c) for c in layer_curves]

    # cycles if there are more layers than colors
    palette = ["firebrick", "royalblue", "green", "darkorange", "purple", "teal", "brown"]

    fig = go.Figure()
    for i, mat in enumerate(materials):
        color = palette[i % len(palette)]
        fig.add_trace(go.Scatter(
            x=t_values, y=layer_curves[i], mode='lines',
            name=f'Layer {i+1}: {mat}', line=dict(color=color, width=2)
        ))
        if low_temp < ranges[i][0]:
            fig.add_vline(x=plotted_ranges[i][0], line_dash="dash", line_color=color, line_width=2.5, annotation_text="Lower Extrapolation Limit", annotation_position="bottom left")
        if high_temp > ranges[i][1]:
            fig.add_vline(x=plotted_ranges[i][1], line_dash="dash", line_color=color, line_width=2.5, annotation_text="Upper Extrapolation Limit", annotation_position="bottom right")

    fig.update_layout(
        title=f"Thermal Conductivity Curves for {', '.join(materials)}",
        xaxis_title=f"{ 'Log ' if log_temp_plot else '' }Temperature (K)",
        yaxis_title=f"{ 'Log ' if log_conductivity_plot else '' }Conductivity (W/m·K)",
        template="plotly_white",
    )

    st.plotly_chart(fig)

st.subheader("Material Shorthand Table")
st.dataframe(df)