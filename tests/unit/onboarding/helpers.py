from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CHECKSUM_HOURS_B = "a0bd220ca3d2738be3a0cdeb1e5c9aa0866e716043ea9bf081637a432c1ab1ab"

DEFAULT_TENANT: dict[str, Any] = {
    "schema_version": 1,
    "slug": "tenant-b",
    "display_name": "Tenant B synthetic",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 1,
    "version": 1,
    "agent": {"tone": "formal"},
    "enabled_skills": ["faq", "appointments"],
    "enabled_tools": [
        "appointments.search",
        "appointments.get",
        "appointments.create",
    ],
    "appointments": {
        "required_fields": ["specialty", "practitioner", "date_from", "date_to"],
    },
    "knowledge": {"namespace": "tenant-b"},
    "mcp": {"server_id": "fake-appointments-b"},
    "handoff": {},
    "feature_flags": {"simulated_channel": True},
}

DEFAULT_INTEGRATIONS: dict[str, Any] = {
    "schema_version": 1,
    "channels": [
        {
            "channel": "simulated",
            "external_account_id": "tenant-b-simulated",
            "secret_reference": "sm://tenant-b/channel/simulated",
        }
    ],
    "integrations": [
        {
            "kind": "mcp",
            "server_id": "fake-appointments-b",
            "credentials_reference": "sm://tenant-b/mcp/appointments",
            "capabilities": [
                "appointments.search",
                "appointments.get",
                "appointments.create",
            ],
        }
    ],
}

DEFAULT_KNOWLEDGE: dict[str, Any] = {
    "schema_version": 1,
    "namespace": "tenant-b",
    "documents": [
        {
            "logical_name": "hours-b",
            "source": "object://synthetic/tenant-b/hours",
            "checksum": CHECKSUM_HOURS_B,
            "mime_type": "text/plain",
        }
    ],
}

DEFAULT_POLICIES: dict[str, dict[str, Any]] = {
    "faq": {"schema_version": 1, "skill": "faq"},
    "appointments": {"schema_version": 1, "skill": "appointments"},
}

DEFAULT_EVALS: list[dict[str, Any]] = [
    {
        "case_id": "tb-faq-001",
        "tenant_fixture": "tenant-b",
        "config_version": 1,
        "expected_skill": "faq",
        "allowed_tools": [],
        "forbidden_tools": ["appointments.create"],
        "messages": [{"role": "user", "text": "horario sucursal norte"}],
    }
]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(current, value)
        else:
            merged[key] = value
    return merged


def write_package(
    root: Path,
    *,
    tenant: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    integrations: dict[str, Any] | None = None,
    knowledge: dict[str, Any] | None = None,
    policies: dict[str, dict[str, Any]] | None = None,
    evals: list[dict[str, Any]] | None = None,
) -> Path:
    tenant_doc = _deep_merge(DEFAULT_TENANT, tenant or {})
    config_doc = _deep_merge(DEFAULT_CONFIG, config or {})
    integrations_doc = _deep_merge(DEFAULT_INTEGRATIONS, integrations or {})
    knowledge_doc = _deep_merge(DEFAULT_KNOWLEDGE, knowledge or {})
    policy_docs = dict(DEFAULT_POLICIES)
    if policies:
        for name, body in policies.items():
            policy_docs[name] = _deep_merge(policy_docs.get(name, {}), body)
    eval_docs = list(evals) if evals is not None else list(DEFAULT_EVALS)

    policies_dir = root / "policies"
    knowledge_dir = root / "knowledge"
    policies_dir.mkdir(parents=True, exist_ok=True)
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    (root / "tenant.yaml").write_text(json.dumps(tenant_doc, indent=2) + "\n")
    (root / "config.yaml").write_text(json.dumps(config_doc, indent=2) + "\n")
    (root / "integrations.yaml").write_text(
        json.dumps(integrations_doc, indent=2) + "\n"
    )
    (knowledge_dir / "manifest.yaml").write_text(
        json.dumps(knowledge_doc, indent=2) + "\n"
    )
    for name, body in policy_docs.items():
        (policies_dir / f"{name}.yaml").write_text(json.dumps(body, indent=2) + "\n")
    (root / "evals.jsonl").write_text(
        "".join(json.dumps(item) + "\n" for item in eval_docs)
    )
    return root
