from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import IO, Any


class JsonLinesWriter:
    def __init__(self, path: str | None = None, pretty: bool = False) -> None:
        self.pretty = pretty
        self._owns_stream = path not in (None, "-")
        self._stream: IO[str]
        if self._owns_stream:
            output_path = Path(path or "camera.jsonl")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream = output_path.open("a", encoding="utf-8", buffering=1)
        else:
            self._stream = sys.stdout

    def write(self, value: dict[str, Any]) -> None:
        if self.pretty:
            text = json.dumps(value, ensure_ascii=False, indent=2)
        else:
            text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        self._stream.write(text + "\n")
        self._stream.flush()

    def close(self) -> None:
        if self._owns_stream:
            self._stream.close()
