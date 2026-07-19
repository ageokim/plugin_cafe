"""`python -m pm` 진입점 (§9.1 — console script 대신 -m 실행)."""

from __future__ import annotations

from pm.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
