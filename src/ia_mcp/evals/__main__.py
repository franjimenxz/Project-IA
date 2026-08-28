from __future__ import annotations

import sys
from pathlib import Path

from ia_mcp.evals.validator import validate_dataset


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] != "validate":
        print(
            "usage: python -m ia_mcp.evals validate <dataset.jsonl>",
            file=sys.stderr,
        )
        return 2
    report = validate_dataset(Path(args[1]))
    print(
        f"valid={str(report.valid).lower()} cases={report.case_count} "
        f"hash={report.dataset_hash}"
    )
    print(
        "use_cases="
        + ",".join(f"{name}:{count}" for name, count in sorted(report.use_case_counts.items()))
    )
    print(
        "tenants="
        + ",".join(f"{name}:{count}" for name, count in sorted(report.tenant_counts.items()))
    )
    print(
        "adversarial="
        + ",".join(
            f"{name}:{count}" for name, count in sorted(report.adversarial_counts.items())
        )
    )
    for issue in report.issues:
        print(issue, file=sys.stderr)
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
