import json
from pathlib import Path

import pytest

from litrelay.measurements import render_measurements, validate_measurements


def test_pint_speed_and_absolute_and_relative_temperatures() -> None:
    units = json.loads((Path(__file__).parents[1] / "examples/measurements-zh-ru.json").read_text())
    validate_measurements(units)
    data = {
        "translation": (
            "60 миль в час[[measure:mph:60]], −4 °F[[measure:fahrenheit:-4]], "
            "на 18 °F теплее[[measure:fahrenheit_change:18]], "
            "от −4 до 32 °F[[measure:fahrenheit:-4-32]]."
        )
    }
    assert json.loads(render_measurements(json.dumps(data), units, "ru"))["translation"] == (
        "60 миль в час [≈96,5606 км/ч], −4 °F [-20 °C], на 18 °F теплее [10 °C], от −4 до 32 °F [-20–0 °C]."
    )


def test_pint_rejects_incompatible_dimensions() -> None:
    with pytest.raises(ValueError, match="Invalid unit conversion"):
        validate_measurements(
            {
                "broken": {
                    "source": "meter",
                    "from_unit": "meter",
                    "to_unit": "second",
                    "symbol": "s",
                    "approximate": False,
                }
            }
        )


def test_vague_measurement_gloss_preserves_unspecified_amount() -> None:
    units = {
        "li": {
            "source": "里",
            "factor": "500",
            "symbol": "м",
            "approximate": True,
            "label": "ли",
        }
    }
    validate_measurements(units)
    output = json.dumps({"translation": "Сотни ли[[measure:li:unit]] вокруг."})
    assert json.loads(render_measurements(output, units, "ru"))["translation"] == "Сотни ли [1 ли ≈ 500 м] вокруг."
