"""User-facing settings: window placement, scale, opacity, theme.

Stored next to diary.json in the platform-appropriate user data dir. Loaded at
startup and applied before the window is shown; saved on exit and whenever the
user changes a value from the sidebar.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .diary import _data_dir


@dataclass
class Settings:
    # Window position on the desktop. None = no saved value, fall back to snap.
    x: Optional[int] = None
    y: Optional[int] = None
    scale_pct: int = 100
    opacity_pct: int = 100
    theme: str = "ambient"  # 'ambient' | 'vivid'
    sidebar_side: str = "left"  # 'left' | 'right'
    hard_drop_threshold: float = 5.0
    # AI playstyle: 'calm' (steady singles), 'tetris' (builds for big clears),
    # 'tspin' (tolerates messy stacks — occasional T-spins via luck).
    ai_mode: str = "tetris"
    # Percent of today's accumulated score deducted on each top-out.
    death_penalty_pct: float = 10.0
    # Fade window opacity after a stretch of no typing, restore on next key.
    idle_fade_enabled: bool = True
    # Hide to tray while another app is in D3D fullscreen / presentation mode.
    fullscreen_autohide_enabled: bool = True

    @classmethod
    def load(cls) -> "Settings":
        path = _settings_path()
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        fields = {f.name for f in cls.__dataclass_fields__.values()}
        clean = {k: v for k, v in raw.items() if k in fields}
        try:
            return cls(**clean)
        except Exception:
            return cls()

    def save(self) -> None:
        path = _settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".settings.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def _settings_path() -> Path:
    return _data_dir() / "settings.json"
