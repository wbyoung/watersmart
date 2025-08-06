"""Test WaterSmart helpers."""

import pytest

from custom_components.watersmart.helpers import parse_hostname


@pytest.mark.parametrize(
    ("value", "result"),
    [
        ("bendoregon", ("bendoregon", None)),
        ("myutility.bellevuewa.gov", ("myutility", "bellevuewa.gov")),
        ("https://myutility.bellevuewa.gov", ("myutility", "bellevuewa.gov")),
    ],
)
def test_parse_hostname(value, result):
    assert parse_hostname(value) == result
