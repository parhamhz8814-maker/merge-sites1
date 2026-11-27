#!/usr/bin/env python3
"""Run the whole CP.Shop backend test suite in one command.

Usage:
    python run_tests.py

Exits 0 only if every suite passes. Prints a per-suite summary at the end.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

SUITES = [
    ("imports + order flow", "check_imports.py"),
    ("shopping cart", "test_shopping_cart.py"),
    ("production DB flow", "test_db_production_flow.py"),
    ("security + DB regression", "test_production_security.py"),
]


def main() -> int:
    results: list[tuple[str, bool, int]] = []

    for label, script in SUITES:
        path = HERE / script
        print()
        print("#" * 70)
        print(f"# {label}  ({script})")
        print("#" * 70)
        proc = subprocess.run(
            [sys.executable, str(path)],
            cwd=str(HERE),
            capture_output=False,
        )
        results.append((label, proc.returncode == 0, proc.returncode))

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    failed = 0
    for label, ok, code in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"  (exit {code})"))
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"RESULT: {failed} of {len(results)} suites FAILED")
        return 1
    print(f"RESULT: ALL {len(results)} SUITES PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
