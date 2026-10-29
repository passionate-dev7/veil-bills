"""Settings. The API key is read from the environment, falling back to ~/.zshrc. Never printed, never logged."""
from __future__ import annotations
import os, re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
LIGHTNING = "nvidia/Nemotron-3_5-Lightning"
ALLOWED_MODELS = (ULTRA, LIGHTNING)  # Super and Nano 30B are deliberately not routable.


def load_api_key() -> str | None:
    k = os.environ.get("NEBIUS_API_KEY")
    if k:
        return k.strip()
    rc = Path.home() / ".zshrc"
    if rc.exists():
        for line in reversed(rc.read_text(errors="ignore").splitlines()):
            m = re.match(r"\s*export\s+NEBIUS_API_KEY=(.+)$", line)
            if m:
                return m.group(1).strip().strip("'\"")
    return None


def load_tavily_key() -> str | None:
    """TAVILY_API_KEY from the environment or ~/.config/nvdia/tavily.env. Never printed, never logged, never committed."""
    k = os.environ.get("TAVILY_API_KEY")
    if k:
        return k.strip()
    f = Path.home() / ".config" / "nvdia" / "tavily.env"
    if f.exists():
        for line in f.read_text(errors="ignore").splitlines():
            m = re.match(r"\s*(?:export\s+)?TAVILY_API_KEY=(.+)$", line)
            if m:
                return m.group(1).strip().strip("'\"")
    return None


@dataclass
class Settings:
    upstream: str = field(default_factory=lambda: os.environ.get("VEIL_UPSTREAM", "https://api.tokenfactory.nebius.com/v1"))
    home: Path = field(default_factory=lambda: Path(os.environ.get("VEIL_HOME", ROOT / ".veil")))
    profile: Path = field(default_factory=lambda: Path(os.environ.get("VEIL_PROFILE", ROOT / "demo" / "profile.json")))
    api_key: str | None = field(default_factory=load_api_key)
    timeout: float = 300.0
    tavily_key: str | None = field(default_factory=load_tavily_key)
    tavily_url: str = "https://api.tavily.com/search"

    @property
    def vault_db(self) -> Path:
        return self.home / "vault.sqlite"

    @property
    def ledger_db(self) -> Path:
        return self.home / "ledger.sqlite"

    @property
    def outbox(self) -> Path:
        return self.home / "outbox"

    @property
    def mailbox(self) -> Path:
        return self.home / "sandbox_mailbox"

    @property
    def memory_db(self) -> Path:
        return self.home / "memory.sqlite"
