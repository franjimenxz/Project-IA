"""Write a tenant package from the lab institution form.

Generated files follow the current package contract. Credentials stay
references (`sm://…`); the writer never stores a secret value.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from ia_mcp.configuration.models import SkillName
from ia_mcp.mcp.registry import KNOWN_TOOLS
from ia_mcp.onboarding.loader import load_yaml
from ia_mcp.onboarding.models import TenantDocument
from ia_mcp.onboarding.validator import TOOL_SKILL_PREFIX, URI_RE

Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
NonEmpty = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]


class InstitucionForm(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: Slug
    display_name: NonEmpty
    tone: NonEmpty
    instructions: str | None = Field(default=None, max_length=2000)
    enabled_skills: frozenset[SkillName] = Field(default_factory=frozenset)
    enabled_tools: frozenset[str] = Field(default_factory=frozenset)
    mcp_server_id: NonEmpty
    mcp_capabilities: frozenset[str] = Field(default_factory=frozenset)
    mcp_credentials_reference: NonEmpty
    knowledge_text: str | None = None

    @field_validator("instructions", "knowledge_text", mode="before")
    @classmethod
    def _omit_blank(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mcp_credentials_reference")
    @classmethod
    def _credentials_are_uri(cls, value: str) -> str:
        if URI_RE.fullmatch(value) is None:
            raise ValueError("mcp_credentials_reference must be a URI")
        return value

    @field_validator("enabled_tools")
    @classmethod
    def _known_tools(cls, value: frozenset[str]) -> frozenset[str]:
        unknown = value - {str(item) for item in KNOWN_TOOLS}
        if unknown:
            raise ValueError("enabled_tools must be known tools")
        return value

    @model_validator(mode="after")
    def _tools_match_capabilities_and_skills(self) -> InstitucionForm:
        missing = self.enabled_tools - self.mcp_capabilities
        if missing:
            raise ValueError("enabled_tools must be declared as MCP capabilities")
        for tool in self.enabled_tools:
            for prefix, skill in TOOL_SKILL_PREFIX:
                if tool.startswith(prefix) and skill not in self.enabled_skills:
                    raise ValueError("tools must belong to enabled skills")
        return self


def display_name_for(packages_dir: Path | None, slug: str) -> str:
    """Read `display_name` from the package, or fall back to the slug."""
    if packages_dir is None:
        return slug
    path = packages_dir / slug / "tenant.yaml"
    if not path.is_file():
        return slug
    try:
        loaded = load_yaml(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return slug
    if isinstance(loaded, dict):
        name = loaded.get("display_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return slug


def write_lab_package(root: Path, form: InstitucionForm) -> Path:
    slug = form.slug
    TenantDocument(schema_version=1, slug=slug, display_name=form.display_name)
    package = root / slug
    policies_dir = package / "policies"
    knowledge_dir = package / "knowledge"
    policies_dir.mkdir(parents=True, exist_ok=True)
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    agent: dict[str, str] = {"tone": form.tone}
    if form.instructions:
        agent["instructions"] = form.instructions

    tenant_doc = {
        "schema_version": 1,
        "slug": slug,
        "display_name": form.display_name,
    }
    config_doc: dict[str, object] = {
        "schema_version": 1,
        "version": 1,
        "agent": agent,
        "enabled_skills": sorted(form.enabled_skills),
        "enabled_tools": sorted(form.enabled_tools),
        "appointments": {},
        "knowledge": {"namespace": slug},
        "mcp": {
            "server_id": form.mcp_server_id,
            "credentials_reference": form.mcp_credentials_reference,
        },
        "handoff": {},
        "feature_flags": {"simulated_channel": True},
    }
    integrations_doc = {
        "schema_version": 1,
        "channels": [
            {
                "channel": "simulated",
                "external_account_id": f"{slug}-simulated",
                "secret_reference": f"sm://{slug}/channel/simulated",
            }
        ],
        "integrations": [
            {
                "kind": "mcp",
                "server_id": form.mcp_server_id,
                "credentials_reference": form.mcp_credentials_reference,
                "capabilities": sorted(form.mcp_capabilities),
            }
        ],
    }
    knowledge_doc: dict[str, object] = {
        "schema_version": 1,
        "namespace": slug,
        "documents": [],
    }
    if form.knowledge_text:
        notes = knowledge_dir / "notes.txt"
        notes.write_text(form.knowledge_text, encoding="utf-8")
        digest = hashlib.sha256(form.knowledge_text.encode("utf-8")).hexdigest()
        knowledge_doc["documents"] = [
            {
                "logical_name": "notes",
                "source": f"object://lab/{slug}/notes",
                "checksum": digest,
                "mime_type": "text/plain",
            }
        ]

    _write_json(package / "tenant.yaml", tenant_doc)
    _write_json(package / "config.yaml", config_doc)
    _write_json(package / "integrations.yaml", integrations_doc)
    _write_json(knowledge_dir / "manifest.yaml", knowledge_doc)
    for skill in form.enabled_skills:
        _write_json(
            policies_dir / f"{skill}.yaml",
            {"schema_version": 1, "skill": skill},
        )
    (package / "evals.jsonl").write_text("", encoding="utf-8")
    return package


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
