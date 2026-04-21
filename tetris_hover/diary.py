"""Per-day diary storage (JSON).

Location:
  Windows: %APPDATA%/tetris-hover/diary.json
  macOS:   ~/Library/Application Support/tetris-hover/diary.json
  Linux:   $XDG_DATA_HOME/tetris-hover/diary.json (or ~/.local/share/...)

File format:
{
  "days": {
    "2026-04-20": {
      "date": "2026-04-20",
      "score": 12345.0,
      "raw_score": 8000.0,
      "lines": 40,
      "pieces": 100,
      "keystrokes": 5000,
      "duration_sec": 7200,
      "active_sec": 3600,
      "max_combo": 5,
      "max_b2b": 3,
      "sessions": 2
    }, ...
  }
}
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from .core.scoring import Session


APP_DIR_NAME = "Petris"
LEGACY_APP_DIR_NAME = "tetris-hover"


def _base_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base)


def _data_dir() -> Path:
    base = _base_dir()
    new = base / APP_DIR_NAME
    legacy = base / LEGACY_APP_DIR_NAME
    if legacy.exists() and not new.exists():
        try:
            legacy.rename(new)
        except Exception:
            pass
    return new


def diary_path() -> Path:
    return _data_dir() / "diary.json"


@dataclass
class DayRecord:
    date: str
    score: float = 0.0
    raw_score: float = 0.0
    lines: int = 0
    pieces: int = 0
    keystrokes: int = 0
    duration_sec: int = 0
    active_sec: int = 0
    max_combo: int = 0
    max_b2b: int = 0
    sessions: int = 0

    @classmethod
    def empty(cls, d: str) -> "DayRecord":
        return cls(date=d)


@dataclass
class Diary:
    days: Dict[str, DayRecord] = field(default_factory=dict)

    @classmethod
    def load(cls) -> "Diary":
        p = diary_path()
        if not p.exists():
            return cls()
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return cls()
        days: Dict[str, DayRecord] = {}
        for k, v in (raw.get("days") or {}).items():
            try:
                days[k] = DayRecord(**{f: v.get(f, DayRecord.empty(k).__dict__[f]) for f in DayRecord.__dataclass_fields__})
            except Exception:
                continue
        return cls(days=days)

    def save(self) -> None:
        p = diary_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {"days": {k: asdict(v) for k, v in self.days.items()}}
        # Write atomically so a crash mid-write doesn't corrupt the file.
        fd, tmp_path = tempfile.mkstemp(dir=str(p.parent), prefix=".diary.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, p)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def merge_session(
        self,
        *,
        today: Optional[str] = None,
        session: Session,
        duration_sec: int,
    ) -> DayRecord:
        d = today or date.today().isoformat()
        rec = self.days.get(d, DayRecord.empty(d))
        rec.score += session.score
        rec.raw_score += session.raw_score
        rec.lines += session.lines
        rec.pieces += session.pieces
        rec.keystrokes += session.keystrokes
        rec.duration_sec += duration_sec
        rec.active_sec += int(session.active_ms / 1000)
        rec.max_combo = max(rec.max_combo, session.max_combo)
        rec.max_b2b = max(rec.max_b2b, session.max_b2b)
        rec.sessions += 1
        self.days[d] = rec
        return rec

    def by_date_desc(self) -> List[DayRecord]:
        return sorted(self.days.values(), key=lambda r: r.date, reverse=True)

    def by_score_desc(self) -> List[DayRecord]:
        return sorted(self.days.values(), key=lambda r: r.score, reverse=True)
