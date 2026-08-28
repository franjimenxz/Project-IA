from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from ia_mcp.observability.redaction import redact
from ia_mcp.onboarding.validator import validate_package


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ia_mcp.onboarding")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("package", type=Path)
    args = parser.parse_args(list(argv) if argv is not None else None)
    report = validate_package(args.package)
    print(redact(report.model_dump_json(indent=2)))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
