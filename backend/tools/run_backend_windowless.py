#!/usr/bin/env python3
"""Run backend/app.py with file-backed stdout/stderr.

This wrapper is intended for Windows background launches where stdout/stderr
should be file-backed. The backend itself is unchanged.
"""

from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path


def main() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    project_root = backend_dir.parent
    log_dir = backend_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    stdout_log = open(log_dir / "backend_stdout.log", "a", encoding="utf-8", buffering=1)
    stderr_log = open(log_dir / "backend_stderr.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = stdout_log
    sys.stderr = stderr_log

    os.environ["FLASK_DEBUG"] = "0"
    os.chdir(project_root)
    sys.path.insert(0, str(backend_dir))
    runpy.run_path(str(backend_dir / "app.py"), run_name="__main__")


if __name__ == "__main__":
    main()
