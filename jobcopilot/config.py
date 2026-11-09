"""Your search profile, read from config.toml (copy config.example.toml to start)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    name: str
    cv_path: Path
    email: str = ""
    portfolio_url: str = ""
    model: str = "claude-opus-5-5"
    role_keywords: list[str] = field(default_factory=list)
    level_keywords: list[str] = field(default_factory=list)
    text_keywords: list[str] = field(default_factory=list)
    exclude_title: list[str] = field(default_factory=list)
    exclude_text: list[str] = field(default_factory=list)
    remote_only: bool = False
    remote_regions: list[str] = field(default_factory=list)
    data_dir: Path = Path("data")
    letters_dir: Path = Path("applications")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "jobs.db"

    def cv_text(self) -> str:
        from jobmatch.documents import load_text
        if not self.cv_path.exists():
            raise FileNotFoundError(
                f"Your CV was not found at {self.cv_path}. Put your CV file there, "
                "or change the `cv = ...` line in config.toml to where it is."
            )
        return load_text(self.cv_path)


def load_config(path: str | Path = "config.toml") -> Config:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Copy config.example.toml to {path} and fill in your details.")
    raw = tomllib.loads(path.read_text(encoding="utf-8-sig"))   # tolerate a Windows BOM
    me, search, ai = raw.get("me", {}), raw.get("search", {}), raw.get("ai", {})
    base = path.parent
    return Config(
        name=me["name"], cv_path=base / me["cv"], email=me.get("email", ""),
        portfolio_url=me.get("portfolio_url", ""), model=ai.get("model", "claude-opus-5-5"),
        role_keywords=[t.lower() for t in search.get("role_keywords", [])],
        level_keywords=[t.lower() for t in search.get("level_keywords", [])],
        text_keywords=[t.lower() for t in search.get("text_keywords", [])],
        exclude_title=[t.lower() for t in search.get("exclude_title", [])],
        exclude_text=[t.lower() for t in search.get("exclude_text", [])],
        remote_only=search.get("remote_only", False), remote_regions=search.get("remote_regions", []),
        data_dir=base / raw.get("paths", {}).get("data", "data"),
        letters_dir=base / raw.get("paths", {}).get("letters", "applications"),
    )
