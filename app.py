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

with st.form("input_form"):
    inner = st.text_input("Inner Material", value="CuRRR100")
    in_radius = st.number_input("Inner Radius (mm)", value=0.29)

    dielectric = st.text_input("Dielectric Material", value="PTFE")
    di_radius = st.number_input("Dielectric Radius (mm)", value=0.94)

    outer = st.text_input("Outer Material", value="SS304")
    out_radius = st.number_input("Outer Radius (mm)", value=1.19)

    low_temp = st.number_input("Low Temperature Stage (K)", value=4.0)
    high_temp = st.number_input("High Temperature Stage (K)", value=50.0)
    length = st.number_input("Length of Cable (mm)", value=320.0)

    # n_intermediate_stages = st.number_input("Number of Intermediate Stages", value = 0, step = 1)

    n_cables = st.number_input("Number of Cables", value=1, step=1)
    
    log_temp_plot = st.checkbox("Plot Temperature Logarithmically?", value=True)
    log_conductivity_plot = st.checkbox("Plot Conductivity Logarithmically?", value=True)

    submitted = st.form_submit_button("Calculate Thermal Load")

df = pd.read_csv("material_shorthand.txt", sep="\t", names = ["Shorthand", "Material", "Valid Temperature Range (K)"])
df = df[["Material", "Shorthand", "Valid Temperature Range (K)"]]

if submitted:
    radii_mm = [in_radius, di_radius, out_radius]
    heat_stages = [(low_temp, high_temp, length)]

    curves = thermal_math.buildCurves(inner, dielectric, outer, heat_stages)
    areas = thermal_math.getAreas(radii_mm)
    q, indiv_q = thermal_math.getThermalLoad(curves, areas, heat_stages, n_cables)

    st.write(f"Inner Load: {indiv_q[0]:.4f} W")
    st.write(f"Dielectric Load: {indiv_q[1]:.4f} W")
    st.write(f"Outer Load: {indiv_q[2]:.4f} W")

    with st.container(border=True):
        st.write(f"Total Thermal Load: {q:.4f} W")
    
    t_values = np.linspace(low_temp, high_temp, 100)
    inner_curve = np.array([curves[0](t) for t in t_values])
    dielectric_curve = np.array([curves[1](t) for t in t_values])
    outer_curve = np.array([curves[2](t) for t in t_values])

    inner_range_text = df.loc[df["Shorthand"] == inner,"Valid Temperature Range (K)"].values[0] # 1K - 300K, 18K - 300K
    dielectric_range_text = df.loc[df["Shorthand"] == dielectric, "Valid Temperature Range (K)"].values[0]
    outer_range_text = df.loc[df["Shorthand"] == outer, "Valid Temperature Range (K)"].values[0]

    inner_range = [int(x) for x in re.findall(r"\d+\.?\d*", inner_range_text)]
    dielectric_range = [int(x) for x in re.findall(r"\d+\.?\d*", dielectric_range_text)]
    outer_range = [int(x) for x in re.findall(r"\d+\.?\d*", outer_range_text)]

    ranges = [inner_range, dielectric_range, outer_range]

    plotted_ranges = ranges

    if log_temp_plot:
        t_values = np.log10(t_values)
        plotted_ranges = [(np.log10(r[0]), np.log10(r[1])) for r in ranges]

    if log_conductivity_plot:
        inner_curve = np.log10(inner_curve)
        dielectric_curve = np.log10(dielectric_curve)
        outer_curve = np.log10(outer_curve)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=t_values,
        y=inner_curve,
        mode='lines',
        name=f'Inner: {inner}',
        line=dict(color='firebrick', width=2)
    ))
    if low_temp < ranges[0][0]:
        fig.add_vline(x=plotted_ranges[0][0], line_dash="dash", line_color="firebrick", line_width=3.5, annotation_text="Lower Extrapolation Limit", annotation_position="bottom left")
    if high_temp > ranges[0][1]:
        fig.add_vline(x=plotted_ranges[0][1], line_dash="dash", line_color="firebrick", line_width=3.5, annotation_text="Upper Extrapolation Limit", annotation_position="bottom right")

    fig.add_trace(go.Scatter(
        x=t_values,
        y=dielectric_curve,
        mode='lines',
        name=f'Dielectric: {dielectric}',
        line=dict(color='royalblue', width=2)
    ))
    if low_temp < ranges[1][0]:
        fig.add_vline(x=plotted_ranges[1][0], line_dash="dash", line_color="royalblue", line_width=2.5, annotation_text="Lower Extrapolation Limit", annotation_position="bottom left")
    if high_temp > ranges[1][1]:
        fig.add_vline(x=plotted_ranges[1][1], line_dash="dash", line_color="royalblue", line_width=2.5, annotation_text="Upper Extrapolation Limit", annotation_position="bottom right")

    fig.add_trace(go.Scatter(
        x=t_values,
        y=outer_curve,
        mode='lines',
        name=f'Outer: {outer}',
        line=dict(color='green', width=2)
    ))
    if low_temp < ranges[2][0]:
        fig.add_vline(x=plotted_ranges[2][0],line_dash="dash",line_color="green",line_width=1.5, annotation_text="Lower Extrapolation Limit", annotation_position="bottom left")
    if high_temp > ranges[2][1]:
        fig.add_vline(x=plotted_ranges[2][1],line_dash="dash",line_color="green",line_width=1.5, annotation_text="Upper Extrapolation Limit", annotation_position="bottom right")

    fig.update_layout(
        title=f"Thermal Conductivity Curves for {inner}, {dielectric}, and {outer}",
        xaxis_title=f"{ 'Log ' if log_temp_plot else '' }Temperature (K)",
        yaxis_title=f"{ 'Log ' if log_conductivity_plot else '' }Conductivity (W/m·K)",
        template="plotly_white",
    )

    st.plotly_chart(fig)

st.subheader("Material Shorthand Table")
st.dataframe(df)