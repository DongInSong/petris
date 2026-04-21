# Petris

A small tetris that plays itself in the corner of your screen. Typing speeds
up the falling blocks and scores points. Daily totals go into a diary file.

Currently Windows only.

## Install

Download `Petris.exe` from the latest release and double-click. Windows
SmartScreen may warn on first launch (the binary is not code-signed). Click
"More info" → "Run anyway".

To start on boot, put a shortcut to `Petris.exe` in the folder you get by
pressing `Win+R` and typing `shell:startup`.

## Build

Requires Python 3.10+ on Windows.

```
py -m pip install -r requirements.txt
py -m PyInstaller --clean --noconfirm Petris.spec
```

Output: `dist\Petris.exe`.

## Controls

Move the mouse over the window to reveal the sidebar. Everything collapses
again when you move away.

| | |
|---|---|
| `▓` handle (top) | drag to move |
| `⏻` | quit (saves diary) |
| `×` | hide to tray |
| `100` | scale. Left-click cycles 50/75/100/125/150. Right-click opens a menu. |
| `◐` | opacity slider popup |
| `↖ ↗ ↙ ↘` | snap to a screen corner |
| `○` / `●` | toggle theme (ambient / vivid) |
| `⋯` | open the diary |

Tray icon: left-click toggles visibility; right-click has show/hide, theme,
snap-to, diary, reset size, and quit.

## How it works

An El-Tetris-style heuristic picks a placement for each piece. Every global
keystroke adds to a boost value that decays over time; sustained typing adds
a combo multiplier on top. The combined multiplier controls rotation speed,
horizontal-move speed, gravity, lock delay, and score weight at the moment
of each line clear.

At a multiplier past the configured threshold (default 5×) the piece skips
the rest of its gravity fall and "slams" to the bottom, with a 500 ms
cooldown between slams.

## Files

All data lives under `%APPDATA%\Petris\`:

- `diary.json` — per-day score, lines, pieces, keystrokes, duration.
- `settings.json` — position, scale, opacity, theme, sidebar side,
  `hard_drop_threshold`.
- `crash.log` — appended on unhandled exceptions.
- `diagnostic.log` — key-hook status, peak multiplier, and slam count,
  sampled every 10 seconds.

To reset everything, close Petris and delete `%APPDATA%\Petris\`.

## Privacy

The global key hook records only timestamps (for rate) and a running count
(for the diary). It does not capture which keys are pressed, and nothing
leaves your machine. All data stays on disk in `%APPDATA%\Petris\`.

If the key hook doesn't pick up typing in a specific app, that app is
probably running with higher privileges than Petris. Run `Petris.exe` as
administrator, or run the target app without elevation.

## License

MIT. See `LICENSE`.

Dependencies bundled at runtime: PySide6 and pynput, both LGPLv3.
PyInstaller dynamically links them.
