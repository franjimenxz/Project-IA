from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_SCALAR_TRUE = {"true", "True", "TRUE", "yes"}
_SCALAR_FALSE = {"false", "False", "FALSE", "no"}
_SCALAR_NULL = {"null", "Null", "NULL", "~"}


@dataclass(frozen=True, slots=True)
class LoadedPackage:
    root: Path
    tenant: Any
    config: Any
    integrations: Any
    knowledge: Any
    policies: dict[str, Any]
    evals: list[Any]
    missing: tuple[str, ...]
    load_errors: tuple[tuple[str, str], ...]


def load_yaml(text: str) -> Any:
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return json.loads(text)
    lines = _prepare_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("yaml document has trailing content")
    return value


def load_package(root: Path) -> LoadedPackage:
    missing: list[str] = []
    load_errors: list[tuple[str, str]] = []
    required = (
        "tenant.yaml",
        "config.yaml",
        "integrations.yaml",
        "knowledge/manifest.yaml",
        "evals.jsonl",
    )
    documents: dict[str, Any] = {}
    for relative in required:
        path = root / relative
        if not path.is_file():
            missing.append(relative)
            continue
        try:
            if relative.endswith(".jsonl"):
                documents[relative] = _load_jsonl(path)
            else:
                documents[relative] = load_yaml(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError) as exc:
            load_errors.append((relative, "invalid document"))
            del exc

    policies: dict[str, Any] = {}
    policies_dir = root / "policies"
    if policies_dir.is_dir():
        for path in sorted(policies_dir.glob("*.yaml")):
            try:
                policies[path.stem] = load_yaml(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                load_errors.append((f"policies/{path.name}", "invalid document"))

    return LoadedPackage(
        root=root,
        tenant=documents.get("tenant.yaml"),
        config=documents.get("config.yaml"),
        integrations=documents.get("integrations.yaml"),
        knowledge=documents.get("knowledge/manifest.yaml"),
        policies=policies,
        evals=list(documents.get("evals.jsonl") or []),
        missing=tuple(missing),
        load_errors=tuple(load_errors),
    )


def _load_jsonl(path: Path) -> list[Any]:
    rows: list[Any] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _prepare_lines(text: str) -> list[tuple[int, str]]:
    prepared: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        content = _strip_comment(raw.lstrip(" "))
        if not content:
            continue
        prepared.append((indent, content))
    return prepared


def _strip_comment(content: str) -> str:
    if content.startswith(("'", '"')):
        return content
    if " #" in content:
        return content.split(" #", 1)[0].rstrip()
    if content.startswith("#"):
        return ""
    return content


def _parse_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[Any, int]:
    if index >= len(lines):
        return None, index
    _, content = lines[index]
    if content.startswith("- "):
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_mapping(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    mapping: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent or content.startswith("- "):
            break
        if line_indent > indent:
            raise ValueError("invalid yaml indent")
        key, separator, rest = content.partition(":")
        if not separator:
            raise ValueError("invalid yaml mapping")
        key = key.strip()
        rest = rest.strip()
        index += 1
        if rest == "":
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
            else:
                value = None
        else:
            value = _parse_scalar(rest)
        mapping[key] = value
    return mapping, index


def _parse_sequence(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[Any], int]:
    items: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent or not content.startswith("- "):
            break
        if line_indent > indent:
            raise ValueError("invalid yaml indent")
        rest = content[2:].strip()
        index += 1
        if rest == "":
            if index < len(lines) and lines[index][0] > indent:
                value, index = _parse_block(lines, index, lines[index][0])
            else:
                value = None
        elif ":" in rest and not rest.startswith(("'", '"')):
            key, _, raw_value = rest.partition(":")
            item: dict[str, Any] = {
                key.strip(): _parse_scalar(raw_value.strip())
                if raw_value.strip()
                else None
            }
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_mapping(lines, index, lines[index][0])
                item.update(nested)
            value = item
        else:
            value = _parse_scalar(rest)
        items.append(value)
    return items, index


def _parse_scalar(text: str) -> Any:
    if text in _SCALAR_NULL:
        return None
    if text in _SCALAR_TRUE:
        return True
    if text in _SCALAR_FALSE:
        return False
    if text in {"{}", "[]"}:
        return json.loads(text)
    if (text.startswith("{") and text.endswith("}")) or (
        text.startswith("[") and text.endswith("]")
    ):
        return json.loads(text)
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text
