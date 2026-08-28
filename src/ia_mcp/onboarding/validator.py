from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from ia_mcp.onboarding.loader import LoadedPackage, load_package
from ia_mcp.onboarding.models import (
    PACKAGE_SCHEMA_VERSION,
    IntegrationsDocument,
    KnowledgeManifest,
    PackageConfig,
    PackageEvalCase,
    PolicyDocument,
    TenantDocument,
    ValidationIssue,
    ValidationReport,
)

REFERENCE_KEYS = frozenset({"secret_reference", "credentials_reference"})
SECRET_MARKERS = ("token", "password", "secret", "api_key", "apikey", "authorization")
URI_RE = re.compile(r"^[a-z][a-z0-9+.-]*://\S+$")
TOOL_SKILL_PREFIX = (("appointments.", "appointments"),)


def validate_package(package: Path) -> ValidationReport:
    root = package.expanduser().resolve()
    issues: list[ValidationIssue] = []
    if not root.is_dir():
        issues.append(
            ValidationIssue(
                path=str(root),
                code="missing_package",
                message="tenant package directory is required",
            )
        )
        return _report(root, issues)

    loaded = load_package(root)
    for relative in loaded.missing:
        issues.append(
            ValidationIssue(
                path=relative,
                code="missing_file",
                message="required package file is missing",
            )
        )
    for relative, _message in loaded.load_errors:
        issues.append(
            ValidationIssue(
                path=relative,
                code="invalid_document",
                message="package document is invalid",
            )
        )
    issues.extend(_secret_issues("integrations.yaml", loaded.integrations))
    issues.extend(_secret_issues("config.yaml", loaded.config))
    issues.extend(_secret_issues("tenant.yaml", loaded.tenant))
    issues.extend(_secret_issues("knowledge/manifest.yaml", loaded.knowledge))
    for name, body in loaded.policies.items():
        issues.extend(_secret_issues(f"policies/{name}.yaml", body))
    for index, row in enumerate(loaded.evals):
        issues.extend(_secret_issues(f"evals.jsonl[{index}]", row))

    for pdf in root.rglob("*.pdf"):
        issues.append(
            ValidationIssue(
                path=str(pdf.relative_to(root)),
                code="versioned_pdf",
                message="confidential PDFs must not be versioned",
            )
        )

    tenant = _parse_model("tenant.yaml", TenantDocument, loaded.tenant, issues)
    config = _parse_model("config.yaml", PackageConfig, loaded.config, issues)
    integrations = _parse_model(
        "integrations.yaml", IntegrationsDocument, loaded.integrations, issues
    )
    knowledge = _parse_model(
        "knowledge/manifest.yaml", KnowledgeManifest, loaded.knowledge, issues
    )
    policies: list[PolicyDocument] = []
    for name, body in loaded.policies.items():
        parsed = _parse_model(f"policies/{name}.yaml", PolicyDocument, body, issues)
        if parsed is not None:
            if parsed.skill != name:
                issues.append(
                    ValidationIssue(
                        path=f"policies/{name}.yaml.skill",
                        code="policy_skill_mismatch",
                        message="policy skill must match file name",
                    )
                )
            policies.append(parsed)
    evals: list[PackageEvalCase] = []
    for index, row in enumerate(loaded.evals):
        parsed_eval = _parse_model(
            f"evals.jsonl[{index}]", PackageEvalCase, row, issues
        )
        if parsed_eval is not None:
            evals.append(parsed_eval)

    if tenant and config and integrations and knowledge:
        issues.extend(
            _cross_file_issues(tenant, config, integrations, knowledge, policies, evals)
        )

    content_hash = _content_hash(loaded)
    return _report(root, issues, content_hash)


def _report(
    root: Path,
    issues: list[ValidationIssue],
    content_hash: str | None = None,
) -> ValidationReport:
    return ValidationReport(
        valid=not issues,
        schema_version=PACKAGE_SCHEMA_VERSION,
        package_path=str(root),
        content_hash=content_hash,
        errors=tuple(issues),
    )


def _parse_model[T: BaseModel](
    path: str,
    model: type[T],
    payload: Any,
    issues: list[ValidationIssue],
) -> T | None:
    if payload is None:
        return None
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        issues.extend(_issues_from_pydantic(path, exc))
        return None


def _issues_from_pydantic(path: str, exc: ValidationError) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for error in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(part) for part in error["loc"])
        message = error["msg"]
        code = str(error["type"])
        if "extra" in code:
            message = f"extra fields are forbidden: {loc}"
        if "schema_version" in loc:
            message = f"schema_version must be {PACKAGE_SCHEMA_VERSION}"
        if "checksum" in loc:
            message = "checksum must be a sha256 hex digest"
        issues.append(
            ValidationIssue(
                path=f"{path}.{loc}" if loc else path,
                code=code,
                message=message,
            )
        )
    return issues


def _is_secret_key(key: str) -> bool:
    if key in REFERENCE_KEYS:
        return False
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_MARKERS)


def _secret_issues(path: str, node: Any) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _walk_secrets(path, node, issues)
    return issues


def _walk_secrets(path: str, node: Any, issues: list[ValidationIssue]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if _is_secret_key(str(key)):
                issues.append(
                    ValidationIssue(
                        path=child,
                        code="secret_literal",
                        message="secret values are forbidden",
                    )
                )
                continue
            if (
                str(key) in REFERENCE_KEYS
                and isinstance(value, str)
                and URI_RE.fullmatch(value) is None
            ):
                issues.append(
                    ValidationIssue(
                        path=child,
                        code="secret_literal",
                        message="secret values are forbidden",
                    )
                )
                continue
            _walk_secrets(child, value, issues)
    elif isinstance(node, list):
        for index, item in enumerate(node):
            _walk_secrets(f"{path}[{index}]", item, issues)


def _cross_file_issues(
    tenant: TenantDocument,
    config: PackageConfig,
    integrations: IntegrationsDocument,
    knowledge: KnowledgeManifest,
    policies: list[PolicyDocument],
    evals: list[PackageEvalCase],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if config.knowledge.namespace != knowledge.namespace:
        issues.append(
            ValidationIssue(
                path="config.yaml.knowledge.namespace",
                code="namespace_mismatch",
                message="knowledge namespace must match manifest namespace",
            )
        )
    if knowledge.namespace != tenant.slug:
        issues.append(
            ValidationIssue(
                path="knowledge/manifest.yaml.namespace",
                code="namespace_mismatch",
                message="knowledge namespace must correspond to tenant slug",
            )
        )

    seen_channels: set[tuple[str, str]] = set()
    for index, channel in enumerate(integrations.channels):
        key = (channel.channel, channel.external_account_id)
        if key in seen_channels:
            issues.append(
                ValidationIssue(
                    path=f"integrations.yaml.channels[{index}]",
                    code="duplicate_channel",
                    message="channel mapping must be unique",
                )
            )
        seen_channels.add(key)

    enabled_skills = frozenset(config.enabled_skills)
    policy_skills = {policy.skill for policy in policies}
    for skill in enabled_skills:
        if skill not in policy_skills:
            issues.append(
                ValidationIssue(
                    path="policies",
                    code="missing_policy",
                    message=f"enabled skill {skill} requires a policy file",
                )
            )

    enabled_tools = frozenset(config.enabled_tools)
    for tool in enabled_tools:
        tool_skill = _skill_for_tool(tool)
        if tool_skill is not None and tool_skill not in enabled_skills:
            issues.append(
                ValidationIssue(
                    path="config.yaml.enabled_tools",
                    code="skill_tool_mismatch",
                    message="tools must belong to enabled skills",
                )
            )

    mcp_ids = {
        item.server_id
        for item in integrations.integrations
        if item.kind == "mcp" and item.server_id is not None
    }
    if config.mcp.server_id not in mcp_ids:
        issues.append(
            ValidationIssue(
                path="config.yaml.mcp.server_id",
                code="mcp_mismatch",
                message="mcp server_id must match an integration",
            )
        )
    capability_tools = {
        tool
        for item in integrations.integrations
        if item.kind == "mcp"
        for tool in item.capabilities
    }
    missing_capabilities = enabled_tools - capability_tools
    if missing_capabilities:
        issues.append(
            ValidationIssue(
                path="integrations.yaml.integrations",
                code="skill_tool_mismatch",
                message="integration capabilities must include enabled tools",
            )
        )

    for index, case in enumerate(evals):
        if case.tenant_fixture != tenant.slug:
            issues.append(
                ValidationIssue(
                    path=f"evals.jsonl[{index}].tenant_fixture",
                    code="eval_tenant_mismatch",
                    message="eval tenant_fixture must match package slug",
                )
            )
        allowed = frozenset(case.allowed_tools)
        forbidden = frozenset(case.forbidden_tools)
        if allowed & forbidden:
            issues.append(
                ValidationIssue(
                    path=f"evals.jsonl[{index}]",
                    code="eval_tool_overlap",
                    message="allowed and forbidden tools must be disjoint",
                )
            )
        if not allowed <= enabled_tools:
            issues.append(
                ValidationIssue(
                    path=f"evals.jsonl[{index}].allowed_tools",
                    code="skill_tool_mismatch",
                    message="eval allowed tools must belong to enabled tools",
                )
            )
    return issues


def _skill_for_tool(tool: str) -> str | None:
    for prefix, skill in TOOL_SKILL_PREFIX:
        if tool.startswith(prefix):
            return skill
    return None


def _content_hash(loaded: LoadedPackage) -> str:
    payload = {
        "tenant": loaded.tenant,
        "config": _omit_secret_literals(loaded.config),
        "integrations": _omit_secret_literals(loaded.integrations),
        "knowledge": loaded.knowledge,
        "policies": loaded.policies,
        "evals": loaded.evals,
    }
    encoded = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _omit_secret_literals(node: Any) -> Any:
    if isinstance(node, dict):
        omitted: dict[str, Any] = {}
        for key, value in node.items():
            if _is_secret_key(str(key)):
                omitted[key] = "[omitted-literal]"
            else:
                omitted[key] = _omit_secret_literals(value)
        return omitted
    if isinstance(node, list):
        return [_omit_secret_literals(item) for item in node]
    return node
