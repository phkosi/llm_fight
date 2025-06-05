import json
import re
from typing import Any


def parse_json_from_text(text: str) -> Any:
    """Extract and parse JSON object from raw text.

    The function handles optional fenced blocks using `````json```` markers and
    also attempts to locate the first JSON object within a longer string.

    Args:
        text: Raw string possibly containing JSON data.

    Returns:
        Parsed Python representation of the JSON object.

    Raises:
        json.JSONDecodeError: If no valid JSON could be extracted.
    """

    if not isinstance(text, str):
        raise json.JSONDecodeError("Input must be string", str(text), 0)

    stripped = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", stripped, re.IGNORECASE | re.DOTALL)
    if fence_match:
        stripped = fence_match.group(1).strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", stripped, 0)

    decoder = json.JSONDecoder()
    try:
        obj, _ = decoder.raw_decode(stripped[start:])
        return obj
    except json.JSONDecodeError as e:
        raise e
