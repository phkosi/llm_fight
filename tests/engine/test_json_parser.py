from src.utils.json_parser import parse_json_from_text


def test_parse_plain_json():
    assert parse_json_from_text('{"a": 1}') == {"a": 1}


def test_parse_fenced_json():
    text = '```json\n{"a": 1}\n```'
    assert parse_json_from_text(text) == {"a": 1}


def test_parse_json_with_extra_text():
    text = 'Here you go:\n{"a": 1}'
    assert parse_json_from_text(text) == {"a": 1}
