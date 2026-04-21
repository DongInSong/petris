# Changelog

## 1.0.0 — 2026-04-21

First public release.

- Auto-playing tetris engine: SRS rotation with wall kicks, 7-bag randomizer,
  hold piece, lock delay with reset cap, T-spin detection, B2B, combo.
- Heuristic AI (El-Tetris weights) that plans placements per piece.
- Global key hook (pynput) feeds a decay-based boost multiplier (1× idle to
  8× with sustain combo). Multiplier drives gravity, rotation/move tempo,
  lock delay, and score weight.
- Hard-drop "slam" above a configurable threshold, with a 500 ms cooldown.
- Frameless translucent window, always on top. Hover reveals a vertical
  sidebar with drag handle, corner snaps, scale, opacity, theme, diary,
  and quit.
- Daily diary aggregating score, lines, pieces, keystrokes, duration,
  active time, max combo, and max B2B. Multiple sessions on the same
  day accumulate.
- Settings (position, scale, opacity, theme, sidebar side) persist across
  runs. Data directory migrates from `tetris-hover` to `Petris`
  automatically.
- System tray icon with show/hide, theme, snap-to, diary, reset size,
  and quit.
- Windows 11 DWM border and rounded corners suppressed for a clean edge.
