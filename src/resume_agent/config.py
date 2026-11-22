import glob
import os
import re
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONFIG_PATH_ENV = "RESUME_AGENT_CONFIG"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_DATA_ROOT = "~/Library/CloudStorage/ProtonDrive-*/2 Need/Career/Resume Agent Data"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ConfigError(Exception):
    pass


class Provider(StrEnum):
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Links(StrictModel):
    github: str
    linkedin: str


class LlmConfig(StrictModel):
    provider: Provider = Provider.CLAUDE_CODE
    model: str | None = None


class Config(StrictModel):
    data_root: Path = Field(default=DEFAULT_DATA_ROOT, validate_default=True)
    name: str
    email: str
    phone: str
    location: str
    links: Links
    home_industry: str
    industry_keywords: dict[str, list[str]]
    default_baseline: str = "general"
    apply_on_my_behalf: bool = False
    email_scan_hours: int = Field(default=6, gt=0)
    llm: LlmConfig = LlmConfig()

    @field_validator("data_root", mode="before")
    @classmethod
    def resolve_data_root(cls, value: str | Path) -> Path:
        return resolve_data_root(str(value))

    @field_validator("email")
    @classmethod
    def check_email(cls, value: str) -> str:
        if not EMAIL_PATTERN.match(value):
            raise ValueError(f"not a valid email address: {value!r}")
        return value

    @model_validator(mode="after")
    def check_home_industry_has_keywords(self) -> "Config":
        if self.home_industry not in self.industry_keywords:
            raise ValueError(
                f"home_industry {self.home_industry!r} has no entry in industry_keywords"
            )
        return self


def resolve_data_root(pattern: str) -> Path:
    path = Path(pattern).expanduser()
    if not path.is_absolute():
        raise ValueError(f"data_root must be an absolute path or start with ~, got {pattern!r}")
    parts = path.parts
    wildcard_indexes = [index for index, part in enumerate(parts) if glob.has_magic(part)]
    if not wildcard_indexes:
        return Path(*parts)

    split = wildcard_indexes[-1] + 1
    prefix = str(Path(*parts[:split]))
    matches = sorted(glob.glob(prefix))
    if len(matches) != 1:
        found = ", ".join(matches) if matches else "none"
        raise ValueError(
            f"data_root pattern {prefix!r} must match exactly one folder, found: {found}"
        )
    return Path(matches[0], *parts[split:])


def config_path() -> Path:
    return Path(os.environ.get(CONFIG_PATH_ENV, DEFAULT_CONFIG_PATH)).expanduser()


def format_validation_error(error: ValidationError) -> str:
    lines = []
    for detail in error.errors():
        location = ".".join(str(part) for part in detail["loc"]) or "config"
        lines.append(f"  {location}: {detail['msg']}")
    return "\n".join(lines)


def load_config(path: Path | None = None) -> Config:
    path = path or config_path()
    if not path.is_file():
        raise ConfigError(
            f"Config not found at {path}. Copy config.example.yaml there and fill it in."
        )

    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except yaml.YAMLError as error:
        raise ConfigError(f"Config at {path} is not valid YAML:\n  {error}") from error
    if not isinstance(raw, dict):
        raise ConfigError(f"Config at {path} must be a YAML mapping.")

    try:
        return Config(**raw)
    except ValidationError as error:
        details = format_validation_error(error)
        raise ConfigError(f"Config at {path} is invalid:\n{details}") from error
