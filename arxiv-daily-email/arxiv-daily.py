"""
Compatibility wrapper.

Preferred entrypoint: run `python arxiv_daily.py` from the repo root.
This wrapper keeps `python arxiv-daily-email/arxiv-daily.py` working.
"""

from __future__ import annotations

import sys
from pathlib import Path


def _bootstrap_repo_root() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo_root))


def main() -> int:
    _bootstrap_repo_root()
    from arxiv_daily import main as root_main

    return int(root_main())


if __name__ == "__main__":
    raise SystemExit(main())

