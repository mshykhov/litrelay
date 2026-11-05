from __future__ import annotations

import json
import re
from decimal import Decimal, localcontext
from fractions import Fraction
from functools import cache

from pint import UnitRegistry
from pint.errors import PintError

MARKER = re.compile(
    r"\[\[measure:([a-z][a-z0-9_]*):([<>=~≤≥]?)(-?\d{1,18}(?:\.\d{1,9})?)(?:-(-?\d{1,18}(?:\.\d{1,9})?))?\]\]"
)


@cache
def _registry() -> UnitRegistry:
    return UnitRegistry(non_int_type=Fraction)


def _convert(number: Fraction, unit: dict) -> Fraction:
    if "factor" in unit:
        return number * Fraction(unit["factor"])
    try:
        return Fraction(_registry().Quantity(number, unit["from_unit"]).to(unit["to_unit"]).magnitude)
    except (PintError, ValueError, ArithmeticError, TypeError) as error:
        raise ValueError(f"Invalid unit conversion: {unit['from_unit']} -> {unit['to_unit']}") from error


def validate_measurements(units: dict) -> None:
    if not isinstance(units, dict):
        raise ValueError("Measurement profile must be an object")
    common = {"source", "symbol", "approximate"}
    for key, unit in units.items():
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", key)
            or not isinstance(unit, dict)
            or set(unit) not in (common | {"factor"}, common | {"from_unit", "to_unit"})
            or any(
                not isinstance(value, str) or not value.strip() for name, value in unit.items() if name != "approximate"
            )
            or not re.fullmatch(r"[^\[\]<>\r\n]{1,24}", unit["symbol"])
            or type(unit["approximate"]) is not bool
        ):
            raise ValueError(f"Invalid measurement definition: {key}")
        if "factor" in unit and (
            not re.fullmatch(r"\d{1,18}(?:\.\d{1,9}|/[1-9]\d{0,17})?", unit["factor"]) or Fraction(unit["factor"]) <= 0
        ):
            raise ValueError(f"Invalid measurement factor: {key}")
        if _convert(Fraction(1), unit) <= _convert(Fraction(0), unit):
            raise ValueError(f"Measurement conversion must be increasing: {key}")


def render_measurements(output: str, units: dict, language: str) -> str:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return output
    if not isinstance(data, dict) or not isinstance(data.get("translation"), str):
        return output

    def replace(match: re.Match[str]) -> str:
        key, qualifier, start, end = match.groups()
        if key not in units or (end and (Fraction(end) < Fraction(start) or qualifier not in {"", "=", "~"})):
            raise ValueError(f"Invalid measurement marker: {match[0]}")
        unit = units[key]
        exact = [_convert(Fraction(n), unit) for n in (start, end) if n is not None]
        with localcontext() as ctx:
            ctx.prec = 3 if unit["approximate"] else 6
            rounded = [Decimal(n.numerator) / Decimal(n.denominator) for n in exact]
        approximate = (
            unit["approximate"]
            or qualifier == "~"
            or any(Fraction(r) != n for r, n in zip(rounded, exact, strict=True))
        )
        values = [format(value.normalize(), "f") for value in rounded]
        if language.lower().split("-")[0] in {"ru", "uk"}:
            values = [value.replace(".", ",") for value in values]
        bound = qualifier if qualifier in {"<", ">", "≤", "≥"} else ""
        prefix = bound + ("≈" if approximate else "")
        return f" [{prefix}{'–'.join(values)} {unit['symbol']}]"

    text = MARKER.sub(replace, data["translation"])
    if "[[measure" in text:
        raise ValueError("Malformed measurement marker")
    data["translation"] = text
    return json.dumps(data, ensure_ascii=False)
