"""I/O utilities for JSON, JSONL, and text file operations.

Provides orjson-accelerated JSON I/O with stdlib fallback, JSONL support,
and numpy-safe serialization. Ported from vantage_platform/infra/io.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

_orjson: Any
try:
    import orjson
    _orjson = orjson
except ImportError:
    _orjson = None


def load_json(path: Path) -> Any:
    """Load JSON from a file using orjson (fast) with stdlib fallback."""
    raw = path.read_bytes()
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw)


def save_json(obj: Any, path: Path, *, pretty: bool = True) -> None:
    """Save an object as JSON using orjson (fast) with stdlib fallback."""
    obj = convert_numpy(obj)
    path.parent.mkdir(parents=True, exist_ok=True)

    if _orjson is not None:
        opts = (
            _orjson.OPT_INDENT_2 | _orjson.OPT_SORT_KEYS
            if pretty
            else _orjson.OPT_SORT_KEYS
        )
        path.write_bytes(_orjson.dumps(obj, option=opts))
    else:
        with open(path, "w") as f:
            json.dump(
                obj, f, indent=2 if pretty else None,
                sort_keys=True, default=str,
            )


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSON Lines file (one JSON object per line). Blank lines skipped."""
    records: list[dict[str, Any]] = []
    raw = path.read_bytes()
    decode = _orjson.loads if _orjson is not None else json.loads
    for line in raw.split(b"\n"):
        line = line.strip()
        if line:
            records.append(decode(line))
    return records


def save_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    """Save a list of dicts as a JSON Lines file."""
    path.parent.mkdir(parents=True, exist_ok=True)

    if _orjson is not None:
        lines = [_orjson.dumps(convert_numpy(r)) for r in records]
        path.write_bytes(b"\n".join(lines) + b"\n")
    else:
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(convert_numpy(r), sort_keys=True, default=str))
                f.write("\n")


def convert_numpy(obj: Any) -> Any:
    """Recursively convert numpy types to native Python for JSON serialization."""
    try:
        import numpy as np
    except ImportError:
        return obj

    if isinstance(obj, dict):
        obj_dict = cast(dict[Any, Any], obj)
        return {convert_numpy(k): convert_numpy(v) for k, v in obj_dict.items()}
    if isinstance(obj, list):
        return [convert_numpy(v) for v in cast(list[Any], obj)]
    if isinstance(obj, tuple):
        return tuple(convert_numpy(v) for v in cast(tuple[Any, ...], obj))
    if isinstance(obj, np.integer):
        return int(cast(Any, obj))
    if isinstance(obj, np.floating):
        return float(cast(Any, obj))
    if isinstance(obj, np.ndarray):
        return cast(Any, obj).tolist()
    if isinstance(obj, np.bool_):
        return bool(cast(Any, obj))
    return obj
