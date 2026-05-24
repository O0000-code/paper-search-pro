"""Config loader: ~/.paper-search-pro/config.yaml merged with defaults from assets/default_config.yaml.

v2.0: only data-source credentials + output + cache + HTML. Budget / state-machine
config removed — those are managed by the main Claude Code agent via SKILL.md.

Security: user config file is auto-chmoded to 0600 on both write and load, since
it holds real API keys. Detected loose permissions (>0600) are tightened in place
with a stderr warning so the user knows it happened.
"""

import os
import stat
import sys
from pathlib import Path
from typing import Optional
import yaml

from .types import Config

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = SKILL_ROOT / "assets" / "default_config.yaml"
USER_CONFIG_DIR = Path.home() / ".paper-search-pro"
USER_CONFIG_PATH = USER_CONFIG_DIR / "config.yaml"
SECURE_MODE = 0o600


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _enforce_secure_mode(path: Path) -> None:
    """Ensure the file is mode 0600. Fix in place + warn if it was looser.

    Best-effort: on filesystems where chmod is a no-op (some FUSE / Windows /
    network mounts) we swallow the error rather than block config load.
    """
    try:
        current = stat.S_IMODE(path.stat().st_mode)
        if current != SECURE_MODE:
            os.chmod(path, SECURE_MODE)
            if current & 0o077:
                print(
                    f"[paper-search-pro] tightened {path} permissions "
                    f"{oct(current)} → 0600 (file holds API keys)",
                    file=sys.stderr,
                )
    except (OSError, NotImplementedError):
        # Filesystem doesn't support chmod (Windows, some network mounts).
        # Better to keep running than to refuse loading.
        pass


def _ensure_user_config() -> None:
    """If user config doesn't exist, copy defaults so the user has a template.

    Always writes / re-locks the file with 0600 permissions so API keys are
    not world-readable on multi-user machines.
    """
    if not USER_CONFIG_PATH.exists():
        USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if DEFAULT_CONFIG_PATH.exists():
            USER_CONFIG_PATH.write_text(
                DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            _enforce_secure_mode(USER_CONFIG_PATH)


def load_config(path: Optional[Path] = None) -> Config:
    """Load merged Config. Defaults < user overrides.

    Side effect: ensures the resolved user config file is 0600 before reading.
    """
    _ensure_user_config()
    resolved = path or USER_CONFIG_PATH
    if resolved.exists():
        _enforce_secure_mode(resolved)
    defaults = _load_yaml(DEFAULT_CONFIG_PATH)
    user = _load_yaml(resolved)
    merged = {**defaults, **{k: v for k, v in user.items() if v is not None}}

    config = Config()
    for key, value in merged.items():
        if hasattr(config, key):
            setattr(config, key, value)
    return config
