from __future__ import annotations

from datetime import date
import json
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import material_catalog
import material_research
import thermal_math


st.set_page_config(page_title="Thermal conductivity integrator", page_icon=":material/thermostat:", layout="wide")


def _secret(name: str) -> str:
    try:
        return str(st.secrets.get(name, ""))
    except FileNotFoundError:
        return ""


@st.cache_data(ttl="1h", max_entries=30, show_spinner=False)
def _cached_search(
    request_values: dict,
    contact_email: str,
    openalex_api_key: str,
    gemini_api_key: str,
    include_gemini: bool,
):
    request = material_research.ResearchRequest(**request_values)
    return material_research.search_sources(
        request,
        contact_email=contact_email,
        openalex_api_key=openalex_api_key,
        gemini_api_key=gemini_api_key,
        include_gemini=include_gemini,
    )


def _source_label(source: dict) -> str:
    year = f" ({source['year']})" if source.get("year") else ""
    provider = f" · {source['discovered_by']}" if source.get("discovered_by") else ""
    return f"{source.get('title', 'Untitled')}{year}{provider}"


def _start_document_review(contents: bytes, content_type: str, filename: str, source: dict, use_gemini: bool) -> None:
    text = material_research.document_to_text(contents, content_type, filename)
    points, note = material_research.extract_tabulated_points(text)
    method = "deterministic_table"
    fit = None
    if not points and use_gemini:
        points, fit, gemini_note = material_research.gemini_extract_data(text, _secret("GEMINI_API_KEY"))
        note = gemini_note or note
        method = "gemini_assisted"
    st.session_state.draft_points = points
    st.session_state.draft_fit = fit
    st.session_state.draft_source = source
    st.session_state.draft_extraction_method = method
    st.session_state.draft_note = note
    st.session_state.draft_version += 1


def _source_dataframe(sources: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Title": source.get("title", ""),
                "Year": source.get("year"),
                "Publisher": source.get("publisher", ""),
                "DOI": source.get("doi", ""),
                "Open access": source.get("is_open_access"),
                "Found by": source.get("discovered_by", ""),
                "Reliability": (source.get("reliability") or (None, "Not ranked"))[1],
                "URL": source.get("pdf_url") or source.get("url", ""),
            }
            for source in sources
        ]
    )


for key, default in {
    "research_sources": [],
    "research_warnings": [],
    "research_request": None,
    "candidates": {},
    "approved_materials": {},
    "draft_points": [],
    "draft_fit": None,
    "draft_source": None,
    "draft_extraction_method": "manual",
    "draft_note": "",
    "draft_version": 0,
}.items():
    st.session_state.setdefault(key, default)


gemini_api_key = _secret("GEMINI_API_KEY")
openalex_api_key = _secret("OPENALEX_API_KEY")
contact_email = _secret("CONTACT_EMAIL")

builtin_catalog = material_catalog.load_builtin_catalog()
catalog = material_catalog.merge_catalog(builtin_catalog, st.session_state.approved_materials)
labels = {material_id: material_catalog.display_label(material_id, record) for material_id, record in catalog.items()}

st.title("Thermal conductivity integrator")
st.write(
    "Calculate conductive heat load by integrating material conductivity over temperature, "
    "or research and review an open-source dataset for a material that is not built in."
)

view = st.segmented_control(
    "Workspace",
    ["Calculate", "Find a material"],
    default="Calculate",
    key="workspace_view",
    label_visibility="collapsed",
)

if view == "Calculate":
    st.subheader("Cable and temperature inputs")
    layer_defaults = [("CuOFHC", 0.29), ("PTFE", 0.94), ("SS304", 1.19)]
    n_layers = st.number_input("Number of layers", min_value=1, value=3, step=1)

    with st.form("input_form"):
        materials = []
        radii_mm = []
        for index in range(int(n_layers)):
            default_material, default_radius = (
                layer_defaults[index] if index < len(layer_defaults) else (next(iter(catalog)), 0.0)
            )
            material_ids = list(catalog)
            default_index = material_ids.index(default_material) if default_material in catalog else 0
            materials.append(
                st.selectbox(
                    f"Layer {index + 1} material",
                    material_ids,
                    index=default_index,
                    format_func=lambda material_id: labels[material_id],
                    key=f"mat_{index}",
                )
            )
            radii_mm.append(
                st.number_input(
                    f"Layer {index + 1} outer radius (mm)",
                    min_value=0.0,
                    value=default_radius,
                    key=f"rad_{index}",
                    format="%0.5f",
                )
            )

        low_temp = st.number_input("Low-temperature stage (K)", min_value=0.000001, value=4.000)
        high_temp = st.number_input("High-temperature stage (K)", min_value=0.000001, value=50.000)
        length = st.number_input("Cable length (mm)", min_value=0.000001, value=320.000)
        n_cables = st.number_input("Number of cables", min_value=1, value=1, step=1)
        log_temp_plot = st.checkbox("Use a logarithmic temperature axis", value=True)
        log_conductivity_plot = st.checkbox("Use a logarithmic conductivity axis", value=True)
        submitted = st.form_submit_button("Calculate thermal load", icon=":material/calculate:")

    if submitted:
        if low_temp >= high_temp:
            st.error("The high-temperature stage must be greater than the low-temperature stage.")
            st.stop()
        if any(radius <= 0 for radius in radii_mm):
            st.error("Every layer radius must be greater than zero.")
            st.stop()
        if any(radii_mm[index] <= radii_mm[index - 1] for index in range(1, len(radii_mm))):
            st.error("Radii must strictly increase from the inner layer outward.")
            st.stop()

        heat_stages = [(low_temp, high_temp, length)]
        try:
            curves = thermal_math.buildCurves(materials, heat_stages, catalog)
            areas = thermal_math.getAreas(radii_mm)
            total_load, individual_loads = thermal_math.getThermalLoad(curves, areas, heat_stages, n_cables)
        except (ValueError, TypeError) as exc:
            st.error(str(exc))
            st.stop()

        for index, material_id in enumerate(materials):
            st.write(f"Layer {index + 1} ({catalog[material_id]['name']}) load: `{individual_loads[index]:.4e} W`")
        with st.container(border=True):
            st.metric("Total thermal load", f"{total_load:.4e} W")

        temperatures = np.geomspace(low_temp, high_temp, 150) if log_temp_plot else np.linspace(low_temp, high_temp, 150)
        layer_curves = [np.array([curve(temperature) for temperature in temperatures]) for curve in curves]
        ranges = thermal_math.getRanges(materials, catalog)
        plotted_temperatures = np.log10(temperatures) if log_temp_plot else temperatures
        plotted_ranges = [(np.log10(low), np.log10(high)) for low, high in ranges] if log_temp_plot else ranges
        plotted_curves = [np.log10(curve) for curve in layer_curves] if log_conductivity_plot else layer_curves

        palette = ["firebrick", "royalblue", "green", "darkorange", "purple", "teal", "brown"]
        figure = go.Figure()
        for index, material_id in enumerate(materials):
            color = palette[index % len(palette)]
            figure.add_trace(
                go.Scatter(
                    x=plotted_temperatures,
                    y=plotted_curves[index],
                    mode="lines",
                    name=f"Layer {index + 1}: {catalog[material_id]['name']}",
                    line={"color": color, "width": 2},
                )
            )
            if low_temp < ranges[index][0]:
                figure.add_vline(x=plotted_ranges[index][0], line_dash="dash", line_color=color)
            if high_temp > ranges[index][1]:
                figure.add_vline(x=plotted_ranges[index][1], line_dash="dash", line_color=color)
        figure.update_layout(
            title="Thermal conductivity curves",
            xaxis_title=f"{'Log ' if log_temp_plot else ''}temperature (K)",
            yaxis_title=f"{'Log ' if log_conductivity_plot else ''}conductivity (W/m·K)",
            template="plotly_white",
        )
        st.plotly_chart(figure)

    st.subheader("Available materials")
    material_rows = [
        {
            "Material": record["name"],
            "ID": material_id,
            "Valid range (K)": f"{record['equation_range_K'][0]:g}–{record['equation_range_K'][1]:g}",
            "Data type": "Reviewed points" if record["fit_type"] == "tabulated_loglog" else record["fit_type"],
            "Status": "Session" if material_id.startswith("user:") else "Built in",
        }
        for material_id, record in catalog.items()
    ]
    st.dataframe(pd.DataFrame(material_rows), hide_index=True)

else:
    st.subheader("Find and review a material dataset")
    st.info(
        "Results are drafts. Verify the specimen, units, source locator, and every numerical value before approval. "
        "This tool never bypasses paywalls and does not estimate points from plotted curves.",
        icon=":material/fact_check:",
    )

    with st.form("research_form"):
        material_name = st.text_input("Material name", placeholder="Example: alumina 99.5%")
        with st.container(horizontal=True):
            desired_low = st.number_input("Desired low temperature (K)", min_value=0.000001, value=4.0)
            desired_high = st.number_input("Desired high temperature (K)", min_value=0.000001, value=300.0)
        with st.container(horizontal=True):
            grade = st.text_input("Grade or composition")
            condition = st.text_input("Condition or heat treatment")
            purity = st.text_input("Purity or RRR")
        with st.container(horizontal=True):
            direction = st.text_input("Measurement direction")
            physical_form = st.text_input("Physical form or density")
        notes = st.text_area("Additional search notes")
        use_gemini_search = st.checkbox(
            "Use Gemini grounded search after scholarly indexes",
            value=bool(gemini_api_key),
            disabled=not bool(gemini_api_key),
            help="Gemini free-tier content may be used by Google to improve its products.",
        )
        search_submitted = st.form_submit_button("Search sources", icon=":material/search:")

    if search_submitted:
        if not material_name.strip() or desired_low >= desired_high:
            st.error("Enter a material name and an increasing desired temperature range.")
        else:
            request_values = {
                "material": material_name,
                "low_temperature_K": desired_low,
                "high_temperature_K": desired_high,
                "grade": grade,
                "condition": condition,
                "purity": purity,
                "direction": direction,
                "form": physical_form,
                "notes": notes,
            }
            with st.status("Searching scholarly indexes and open sources…", expanded=True) as status:
                sources, warnings = _cached_search(
                    request_values, contact_email, openalex_api_key, gemini_api_key, use_gemini_search
                )
                status.update(label=f"Found {len(sources)} distinct sources", state="complete")
            st.session_state.research_request = request_values
            st.session_state.research_sources = sources
            st.session_state.research_warnings = warnings

    for warning in st.session_state.research_warnings:
        st.warning(warning)

    sources = st.session_state.research_sources
    if sources:
        st.dataframe(
            _source_dataframe(sources),
            hide_index=True,
            column_config={"URL": st.column_config.LinkColumn("URL")},
        )
        selected_index = st.selectbox(
            "Source to inspect",
            range(len(sources)),
            format_func=lambda index: _source_label(sources[index]),
        )
        selected_source = sources[selected_index]
        use_gemini_extract = st.checkbox(
            "Use Gemini only if deterministic table extraction finds nothing",
            value=bool(gemini_api_key),
            disabled=not bool(gemini_api_key),
            help="Only relevant extracted text is sent. Graph points are never estimated.",
        )
        if st.button("Retrieve and inspect source", icon=":material/document_search:"):
            try:
                source = selected_source.copy()
                if source.get("doi") and contact_email:
                    open_access = material_research.lookup_open_access(source["doi"], contact_email)
                    source.update({key: value for key, value in open_access.items() if value})
                source_url = source.get("pdf_url") or source.get("url")
                if not source_url:
                    raise material_research.ResearchError("This result does not include a retrievable URL.")
                with st.status("Retrieving and extracting the selected source…", expanded=True) as status:
                    contents, content_type, final_url = material_research.fetch_public_document(source_url)
                    source["url"] = final_url
                    source["accessed_on"] = date.today().isoformat()
                    _start_document_review(contents, content_type, final_url, source, use_gemini_extract)
                    status.update(label="Source ready for review", state="complete")
            except material_research.ResearchError as exc:
                st.error(str(exc))

    with st.expander("Use a specific URL or upload a legally obtained PDF"):
        direct_url = st.text_input("Public source URL", key="direct_source_url")
        direct_title = st.text_input("Source title", key="direct_source_title")
        direct_doi = st.text_input("DOI (optional)", key="direct_source_doi")
        upload = st.file_uploader("PDF or text/HTML document", type=["pdf", "txt", "html", "htm"])
        use_gemini_upload = st.checkbox(
            "Allow Gemini fallback for this document",
            value=False,
            disabled=not bool(gemini_api_key),
            help="Free-tier content may be used by Google to improve its products.",
        )
        with st.container(horizontal=True):
            if st.button("Inspect URL", disabled=not bool(direct_url.strip())):
                try:
                    contents, content_type, final_url = material_research.fetch_public_document(direct_url)
                    source = {
                        "title": direct_title or final_url,
                        "url": final_url,
                        "doi": direct_doi,
                        "source_type": "user_supplied",
                        "accessed_on": date.today().isoformat(),
                    }
                    _start_document_review(contents, content_type, final_url, source, use_gemini_upload)
                except material_research.ResearchError as exc:
                    st.error(str(exc))
            if st.button("Inspect upload", disabled=upload is None):
                try:
                    source = {
                        "title": direct_title or upload.name,
                        "url": direct_url,
                        "doi": direct_doi,
                        "source_type": "user_upload",
                        "accessed_on": date.today().isoformat(),
                    }
                    _start_document_review(upload.getvalue(), upload.type or "application/octet-stream", upload.name, source, use_gemini_upload)
                except material_research.ResearchError as exc:
                    st.error(str(exc))

    with st.expander("Manually transcribe a published supported fit"):
        with st.form("published_fit_form"):
            published_name = st.text_input("Material name", value=material_name or "")
            published_fit_type = st.selectbox("Published fit family", sorted(material_catalog.BUILTIN_FIT_TYPES))
            published_coefficients = st.text_area(
                "Coefficients in the published order",
                placeholder="Comma-separated numbers, for example: 0.12, 1.84",
            )
            with st.container(horizontal=True):
                published_low = st.number_input("Published lower limit (K)", min_value=0.000001, value=4.0)
                published_high = st.number_input("Published upper limit (K)", min_value=0.000001, value=300.0)
            published_rrr = st.number_input(
                "RRR (only for OFHC_RRR_Wc)", min_value=0.0, value=0.0, help="Leave at zero for other fit families."
            )
            published_title = st.text_input("Source title")
            published_url = st.text_input("Source URL")
            published_doi = st.text_input("Source DOI")
            published_locator = st.text_input("Equation/page/table locator")
            published_notes = st.text_area("Transcription notes")
            published_submitted = st.form_submit_button("Validate published fit")
        if published_submitted:
            try:
                coefficient_values = [float(value.strip()) for value in published_coefficients.split(",") if value.strip()]
                request_values = st.session_state.research_request
                details = (
                    material_research.ResearchRequest(**request_values).material_details() if request_values else {}
                )
                candidate = material_catalog.create_published_material(
                    name=published_name,
                    fit_type=published_fit_type,
                    coefficients=coefficient_values,
                    equation_range_K=[published_low, published_high],
                    source={
                        "title": published_title,
                        "url": published_url,
                        "doi": published_doi,
                        "locator": published_locator,
                        "source_type": "user_transcribed",
                        "accessed_on": date.today().isoformat(),
                    },
                    material_details=details,
                    extraction_method="manual_transcription",
                    notes=published_notes,
                    rrr=published_rrr or None,
                )
                st.session_state.candidates[candidate["material_id"]] = candidate
                st.success("Published fit validated as a draft. Review it below before approval.")
            except (material_catalog.CatalogError, TypeError, ValueError) as exc:
                st.error(str(exc))

    if st.session_state.draft_source is not None:
        st.subheader("Review extracted or manually entered points")
        st.caption(st.session_state.draft_note or "No table was detected. Enter reviewed points manually.")
        if st.session_state.draft_fit:
            st.success("A supported published fit was found. Verify its family, coefficient order, range, and source locator.")
            st.json(st.session_state.draft_fit)
        initial_points = st.session_state.draft_points or [
            {"temperature_K": None, "conductivity_W_mK": None},
            {"temperature_K": None, "conductivity_W_mK": None},
        ]
        point_frame = pd.DataFrame(initial_points)
        edited_points = st.data_editor(
            point_frame,
            key=f"point_editor_{st.session_state.draft_version}",
            num_rows="dynamic",
            hide_index=True,
            column_config={
                "temperature_K": st.column_config.NumberColumn("Temperature (K)", min_value=0.0, format="%.8g"),
                "conductivity_W_mK": st.column_config.NumberColumn(
                    "Conductivity (W/m·K)", min_value=0.0, format="%.8g"
                ),
            },
        )
        request_values = st.session_state.research_request or {
            "material": material_name or "User material",
            "low_temperature_K": desired_low,
            "high_temperature_K": desired_high,
            "grade": grade,
            "condition": condition,
            "purity": purity,
            "direction": direction,
            "form": physical_form,
            "notes": notes,
        }
        candidate_name = st.text_input("Dataset material name", value=request_values["material"], key="candidate_name")
        review_notes = st.text_area("Review notes", key="candidate_review_notes")
        if st.button("Validate candidate", type="primary", icon=":material/checklist:"):
            try:
                points = [
                    {"temperature_K": row["temperature_K"], "conductivity_W_mK": row["conductivity_W_mK"]}
                    for row in edited_points.to_dict("records")
                    if pd.notna(row.get("temperature_K")) or pd.notna(row.get("conductivity_W_mK"))
                ]
                request = material_research.ResearchRequest(**request_values)
                extracted_fit = st.session_state.draft_fit
                if extracted_fit and not points:
                    rrr = extracted_fit.get("rrr") or None
                    candidate = material_catalog.create_published_material(
                        name=candidate_name,
                        fit_type=extracted_fit["fit_type"],
                        coefficients=extracted_fit["coefficients"],
                        equation_range_K=extracted_fit["equation_range_K"],
                        source=st.session_state.draft_source,
                        material_details=request.material_details(),
                        extraction_method=st.session_state.draft_extraction_method,
                        notes=" ".join(filter(None, [st.session_state.draft_note, review_notes])),
                        rrr=rrr,
                    )
                else:
                    candidate = material_catalog.create_tabulated_material(
                        name=candidate_name,
                        points=points,
                        source=st.session_state.draft_source,
                        material_details=request.material_details(),
                        extraction_method=st.session_state.draft_extraction_method,
                        notes=" ".join(filter(None, [st.session_state.draft_note, review_notes])),
                    )
                st.session_state.candidates[candidate["material_id"]] = candidate
                st.success("Candidate validated. Inspect it below before approving it for calculation.")
            except (material_catalog.CatalogError, TypeError, ValueError) as exc:
                st.error(str(exc))

    st.subheader("Candidate datasets")
    if not st.session_state.candidates:
        st.caption("No validated candidates in this session yet.")
    for candidate_id, candidate in list(st.session_state.candidates.items()):
        with st.container(border=True):
            st.write(f"**{candidate['name']}** · `{candidate_id}`")
            source = candidate["source"]
            if source.get("url"):
                st.markdown(f"Source: [{source.get('title', source['url'])}]({source['url']})")
            else:
                st.write(f"Source: {source.get('title', 'User supplied')}")
            data_summary = (
                f"{len(candidate['points'])} reviewed points"
                if candidate["fit_type"] == "tabulated_loglog"
                else f"Published {candidate['fit_type']} fit with {len(candidate['coefficients'])} coefficients"
            )
            st.caption(
                f"{data_summary} · {candidate['equation_range_K'][0]:g}–{candidate['equation_range_K'][1]:g} K · "
                f"{candidate.get('extraction', {}).get('method', 'manual')}"
            )
            if candidate["fit_type"] == "tabulated_loglog":
                preview = pd.DataFrame(candidate["points"]).rename(
                    columns={"temperature_K": "Temperature (K)", "conductivity_W_mK": "Conductivity (W/m·K)"}
                )
                st.line_chart(preview, x="Temperature (K)", y="Conductivity (W/m·K)")
            with st.container(horizontal=True):
                if st.button("Approve for this session", key=f"approve_{candidate_id}", icon=":material/verified:"):
                    approved = json.loads(json.dumps(candidate))
                    approved["review_status"] = "approved"
                    st.session_state.approved_materials[candidate_id] = approved
                    st.rerun()
                if st.button("Remove draft", key=f"remove_{candidate_id}", icon=":material/delete:"):
                    del st.session_state.candidates[candidate_id]
                    st.session_state.approved_materials.pop(candidate_id, None)
                    st.rerun()

    st.subheader("Import or export reviewed bundles")
    imported_file = st.file_uploader("Import a material bundle", type=["json"], key="bundle_upload")
    if st.button("Validate imported bundle", disabled=imported_file is None):
        try:
            imported = material_catalog.import_bundle(imported_file.getvalue())
            for candidate in imported:
                st.session_state.candidates[candidate["material_id"]] = candidate
            st.success(f"Imported {len(imported)} candidates as drafts. Review and approve them above.")
        except material_catalog.CatalogError as exc:
            st.error(str(exc))

    if st.session_state.approved_materials:
        bundle = material_catalog.export_bundle(list(st.session_state.approved_materials.values()))
        st.download_button(
            "Download approved session materials",
            bundle,
            file_name="reviewed_thermal_materials.json",
            mime="application/json",
            icon=":material/download:",
        )
        st.success(f"{len(st.session_state.approved_materials)} session material(s) are available in Calculate.")
    else:
        st.caption("Approved materials are temporary until exported; closing the browser session removes them.")
