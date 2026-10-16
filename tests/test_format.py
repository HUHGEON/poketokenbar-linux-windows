import pytest

from poketokenbar import format as fmt


@pytest.mark.parametrize(
    "value,expected",
    [
        (987, "987"),
        (0, "0"),
        (999, "999"),
        (1_000, "1K"),
        (12_345, "12.3K"),
        (190_612_940, "190.6M"),
        (1_240_000_000, "1.24B"),
        (-12_345, "-12.3K"),
    ],
)
def test_compact_matches_swift_formatter(value, expected):
    assert fmt.compact(value) == expected


def test_compact_trims_trailing_zeros():
    # 1_000_000 -> "1M", not "1.0M"
    assert fmt.compact(1_000_000) == "1M"


@pytest.mark.parametrize(
    "usd,expected",
    [(9.5, "$9.5"), (99.94, "$99.9"), (311.0, "$311"), (1_200.0, "$1200"), (12_000.0, "$12.0K")],
)
def test_cost_compact_matches_swift_thresholds(usd, expected):
    assert fmt.cost_compact(usd) == expected


def test_percent_drops_decimal_when_whole():
    assert fmt.percent(80.0) == "80%"
    assert fmt.percent(80.5) == "80.5%"


# --- rounding boundaries (upstream 4cab9f0, 711fca7) ------------------------


@pytest.mark.parametrize("value,expected", [
    (999, "999"), (1_000, "1K"),
    (999_949, "999.9K"), (999_950, "1M"), (999_999, "1M"), (1_000_000, "1M"),
    (999_949_999, "999.9M"), (999_950_000, "1B"), (999_999_999, "1B"),
    (1_240_000_000, "1.24B"),
])
def test_a_unit_is_promoted_where_its_rounded_text_would_overflow(value, expected):
    """K and M carry one decimal, so the band has to end where that decimal
    would read "1000.0K" rather than at the round number."""
    assert fmt.compact(value) == expected
    assert fmt.compact(-value) == ("-" + expected if value >= 1000 else str(-value))


@pytest.mark.parametrize("value,expected", [
    (80.0, "80%"), (79.96, "80%"), (88.35, "88.3%"), (7.0, "7%"), (99.99, "100%"),
])
def test_a_percentage_drops_its_decimal_on_the_rounded_text(value, expected):
    """Branching on the raw value printed "80.0%" for 79.96 — the branch said
    it was not a round number and the text said it was."""
    assert fmt.percent(value) == expected


@pytest.mark.parametrize("usd,expected", [
    (9.94, "$9.9"), (99.94, "$99.9"), (99.96, "$100"), (100.0, "$100"),
    (9999.4, "$9999"), (9999.6, "$10.0K"),
])
def test_a_compact_cost_picks_its_band_from_what_it_would_print(usd, expected):
    assert fmt.cost_compact(usd) == expected
