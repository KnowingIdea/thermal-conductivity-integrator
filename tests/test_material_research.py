import material_research


def test_request_contains_specimen_details_and_range():
    request = material_research.ResearchRequest(
        material="alumina", low_temperature_K=4, high_temperature_K=300, grade="99.5%", direction="normal"
    )
    assert "99.5%" in request.query()
    assert "4 K 300 K" in request.query()
    assert request.material_details() == {"grade": "99.5%", "direction": "normal"}


def test_deterministic_table_extraction_and_units():
    text = """
    Thermal conductivity measurements
    Temperature (K)    Conductivity (mW/m K)
    4.0    125
    10.0    250
    20.0    500
    Notes follow.
    """
    points, note = material_research.extract_tabulated_points(text)
    assert len(points) == 3
    assert points[0] == {"temperature_K": 4.0, "conductivity_W_mK": 0.125}
    assert "verify" in note.lower()


def test_unlabeled_numbers_are_not_extracted():
    points, _ = material_research.extract_tabulated_points("2020  14\n4.0  0.1\n10  0.2")
    assert points == []


def test_source_deduplication_prefers_nonempty_metadata():
    sources = material_research.deduplicate_sources(
        [
            {"doi": "10.1/example", "title": "Paper"},
            {"doi": "10.1/example", "url": "https://example.org", "year": 2024},
        ]
    )
    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.org"


def test_source_ranking_is_transparent_and_prioritizes_official_sources():
    sources = material_research.deduplicate_sources(
        [
            {"title": "Blog", "url": "https://example.org/blog", "source_type": "web"},
            {"title": "NIST", "url": "https://trc.nist.gov/data", "source_type": "curated"},
        ]
    )
    assert sources[0]["title"] == "NIST"
    assert sources[0]["reliability"][1] == "Official/government"
