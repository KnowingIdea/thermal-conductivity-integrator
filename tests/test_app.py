from streamlit.testing.v1 import AppTest


def test_app_starts_on_calculator_without_exceptions():
    app = AppTest.from_file("app.py", default_timeout=10).run()
    assert not app.exception
    assert app.title[0].value == "Thermal conductivity integrator"
    assert app.selectbox[0].value == "CuOFHC"
