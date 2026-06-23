"""Unit tests for pdga.com parsing helpers."""
from pipeline.pdga import clean_player_name


def test_strips_trailing_pdga_number_suffix():
    # Real pdga.com <title> is e.g. "Casey Clark #167210 | Professional Disc Golf Association".
    assert clean_player_name("Casey Clark #167210") == "Casey Clark"


def test_leaves_a_plain_name_untouched():
    assert clean_player_name("Pat Greenville") == "Pat Greenville"


def test_handles_short_numbers_and_extra_space():
    assert clean_player_name("Jane Doe  #4 ") == "Jane Doe"
