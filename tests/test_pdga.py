"""Unit tests for pdga.com parsing helpers."""
from pipeline.pdga import clean_player_name, extract_photo_url


def test_extracts_player_photo_url():
    html = '<img typeof="foaf:Image" src="https://www.pdga.com/files/styles/large/public/pictures/picture-1.jpg?itok=x">'
    assert extract_photo_url(html) == "https://www.pdga.com/files/styles/large/public/pictures/picture-1.jpg?itok=x"


def test_no_photo_returns_none_and_ignores_site_logo():
    html = '<img src="https://www.pdga.com/sites/all/themes/pdga/logo.png">'
    assert extract_photo_url(html) is None


def test_strips_trailing_pdga_number_suffix():
    # Real pdga.com <title> is e.g. "Casey Clark #167210 | Professional Disc Golf Association".
    assert clean_player_name("Casey Clark #167210") == "Casey Clark"


def test_leaves_a_plain_name_untouched():
    assert clean_player_name("Pat Greenville") == "Pat Greenville"


def test_handles_short_numbers_and_extra_space():
    assert clean_player_name("Jane Doe  #4 ") == "Jane Doe"
