# Changelog

## 1.0.3 — 2026-06-11

- Overhaul AI mode logic. Measured over 10 games × 300 pieces (raw
  score per 100 pieces): **tetris** 5,430 → 8,057 (+48%, 4-line clears
  19 → 177), **tspin** 7,672 → 10,785 (+41%, full T-spins 86 → 201);
  calm unchanged. Zero top-outs in all modes at 1×–6× speed.
  - tetris: fix a scoring distortion where row-transition penalties paid
    the AI +6 to dump blocks into the well; reward tetris-ready rows
    (cols 0–8 full, well empty) instead of min-column depth; bank the I
    piece in hold and fire it the moment a 4-line clear is available;
    penalize interior wells and well-column garbage.
  - tspin: hold the T through worthless mini T-spin zeros; weight
    full-shaped T-slots over mini-shaped ones when preserving setups;
    align the planner's T-spin score table with the engine's actual
    payouts; fix line-count simulation for kicked entries.
  - all modes: panic fallback to survival weights when the stack nears
    the ceiling.
- `scripts/tspin_test.py` now reports raw score and the 1/2/3/4-line
  clear distribution.

## 1.0.2 — 2026-05-08

- Add **Start with Windows** toggle to the tray menu. Registers a Task
  Scheduler logon trigger with `HighestAvailable` run level so an elevated
  launch survives reboots (the simpler HKCU Run key would lose elevation
  and break keystroke capture from UAC-elevated apps via UIPI). Toggling
  prompts UAC; querying state does not. Available only in the packaged
  exe — disabled with a tooltip in dev runs.

## 1.0.1 — 2026-04-26

- Fix popup menus (scale `%` right-click, tray) rendering invisible
  black-on-black text. The window and sidebar's `background: transparent`
  rules were unscoped and cascaded into descendant menu popups; both are
  now scoped to their owning widgets.
- Redesign the diary dialog: compact dark layout with summary cards
  (total / best day / play time / days), segmented sort toggle, podium
  colors for the top 3 in score view.
- Split the README into English (`README.md`) and Korean (`README.ko.md`)
  with a top-of-page language switcher.

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
