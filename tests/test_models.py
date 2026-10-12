from decimal import Decimal

import pytest

from dowidget.models import remaining_percentage


@pytest.mark.parametrize("used,expected", [(0, "100"), (25, "75"), (100, "0"),
                                          (101, "0"), (-1, "100"),
                                          ("12.3456789", "87.6543211")])
def test_used_percent(used, expected):
    assert remaining_percentage(used_percent=used) == Decimal(expected)


@pytest.mark.parametrize("used,total,expected", [(0, 10, "100"), (1, 4, "75"),
                                                (10, 10, "0"), (20, 10, "0"),
                                                ("0.25", "1", "75")])
def test_used_total(used, total, expected):
    assert remaining_percentage(used=used, total=total) == Decimal(expected)


@pytest.mark.parametrize("value", [None, True, False, "bad", "NaN", "Infinity", "-Infinity", float("nan")])
def test_invalid_used_percent_stays_unknown(value):
    assert remaining_percentage(used_percent=value) is None


@pytest.mark.parametrize("used,total", [(None, 10), (1, None), (-1, 10), (1, 0),
                                       (1, -1), (True, 10), (1, False),
                                       ("NaN", 10), (1, "Infinity"), ("bad", 10)])
def test_invalid_fraction_stays_unknown(used, total):
    assert remaining_percentage(used=used, total=total) is None


def test_percent_precedence_and_valid_fraction_fallback():
    assert remaining_percentage(used_percent=20, used=1, total=4) == Decimal(80)
    assert remaining_percentage(used_percent=None, used=1, total=4) == Decimal(75)
    assert remaining_percentage(used_percent="NaN", used=1, total=4) == Decimal(75)
    assert remaining_percentage() is None


def test_extreme_finite_values_clamp_without_decimal_overflow():
    assert remaining_percentage(used_percent="1e999999999") == Decimal(0)
    assert remaining_percentage(used_percent="-1e999999999") == Decimal(100)
    assert remaining_percentage(used="1e999999999", total="1e-999999999") == Decimal(0)
