from typing import Any


def _shorten(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "..."


def format_observation(value: Any, max_items: int = 5, max_chars: int = 1800) -> str:
    print("[observation] format observation")

    if isinstance(value, list):
        rows = [f"Tool returned {len(value)} result(s)."]
        for index, item in enumerate(value[:max_items], start=1):
            if isinstance(item, dict):
                source = item.get("source") or item.get("path") or "unknown"
                score = item.get("score", "n/a")
                snippet = item.get("snippet") or item.get("text") or str(item)
                rows.append(
                    f"{index}. source={source}, score={score}, snippet={_shorten(str(snippet), 360)}"
                )
            else:
                rows.append(f"{index}. {_shorten(str(item), 360)}")
        return _shorten("\n".join(rows), max_chars)

    if isinstance(value, dict):
        if "answer" in value:
            return _shorten(str(value["answer"]), max_chars)
        return _shorten(str(value), max_chars)

    return _shorten(str(value), max_chars)

