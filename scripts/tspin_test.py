#!/usr/bin/env python3
"""Headless T-spin success-rate test.

Replays the AI through a faithful simulation of app.py's frame loop:
- Actions consumed at move_interval, gravity ticks at gravity_interval, lock
  delay countdown — all at the same rates used in the real app.
- For every locked piece, we compare what the AI *planned* (T-spin or normal)
  against what the engine *detected* (t_spin field on ClearEvent).

A T-spin plan that doesn't fire reveals one of two things:
  1. Algorithm bug — the planned pose isn't actually a T-spin pose.
  2. Timing failure — gravity / lock-delay / slam intervened so the final
     rotation either didn't run or wasn't the most-recent action at lock.

Usage:
  python3 scripts/tspin_test.py                       # default: 5 games × 200 pieces
  python3 scripts/tspin_test.py --games 20 --pieces 300
  python3 scripts/tspin_test.py --multiplier 4 --verbose
  python3 scripts/tspin_test.py --mode tetris         # different AI mode
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Make the package importable when running from the repo root.
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from tetris_hover.core.game import Game, ClearEvent, TopOutEvent, LOCK_DELAY_MS
from tetris_hover.ai.player import plan, plan_to_actions, Plan

# Mirror the timing constants from tetris_hover.app so this is faithful.
GRAVITY_BASE_MS = 500
MIN_GRAVITY_MS = 40
MOVE_BASE_MS = 120
MIN_MOVE_MS = 25
SLAM_COOLDOWN_MS = 500
HARD_DROP_THRESHOLD = 5.0  # default settings.hard_drop_threshold


def gravity_interval_ms(mult: float) -> float:
    m = max(0.1, mult)
    if m < HARD_DROP_THRESHOLD:
        return max(MIN_GRAVITY_MS, GRAVITY_BASE_MS / (m ** 1.5))
    base_at_thresh = GRAVITY_BASE_MS / (HARD_DROP_THRESHOLD ** 1.5)
    over = m - HARD_DROP_THRESHOLD
    slowdown = min(150.0, (over * over) * 100.0)
    return base_at_thresh + slowdown


def move_interval_ms(mult: float) -> float:
    return max(MIN_MOVE_MS, MOVE_BASE_MS / max(0.1, mult))


def step_action(game: Game, action: str) -> None:
    if action == 'cw':
        game.rotate(1)
    elif action == 'ccw':
        game.rotate(-1)
    elif action == 'left':
        game.move(-1)
    elif action == 'right':
        game.move(1)
    elif action == 'soft_drop':
        while game.soft_drop():
            pass
    elif action == 'hold':
        game.swap_hold()


def run_game(seed: int, mode: str, max_pieces: int, mult: float, verbose: bool):
    """Run one game and return per-piece records + death count.

    Each record is a tuple:
      (piece_kind, planned_tspin_kind, planned_use_hold, actual_tspin_kind, lines_cleared)
    """
    game = Game(seed=seed)
    records = []
    deaths = 0
    pieces_processed = 0

    move_accum = 0.0
    grav_accum = 0.0
    last_slam_ms = -1e9
    sim_ms = 0.0
    dt = 4.0  # simulation step in ms — ≈ 250fps inner loop, fine-grained
    current_plan: Plan | None = None
    action_queue: list[str] = []
    last_planned: Plan | None = None  # what we planned for the *current* live piece

    while pieces_processed < max_pieces:
        if game.piece is None and game.death_remaining_ms == 0:
            break

        # Plan when needed.
        if not action_queue and current_plan is None and game.piece is not None:
            p = plan(game, mode=mode)
            if p is None:
                break
            current_plan = p
            last_planned = p
            action_queue = plan_to_actions(game, p)

        # Move dispatcher: one action per move_interval.
        move_accum += dt
        m_iv = move_interval_ms(mult)
        while move_accum >= m_iv:
            move_accum -= m_iv
            if action_queue:
                a = action_queue.pop(0)
                if a == 'hold':
                    step_action(game, a)
                    current_plan = None
                    action_queue = []
                else:
                    step_action(game, a)
            elif current_plan is None and game.piece is not None:
                p = plan(game, mode=mode)
                if p is None:
                    break
                current_plan = p
                last_planned = p
                action_queue = plan_to_actions(game, p)

        # Gravity dispatcher.
        grav_accum += dt
        g_iv = gravity_interval_ms(mult)
        while grav_accum >= g_iv:
            grav_accum -= g_iv
            if game.piece is not None:
                game.soft_drop()

        # Slam if AI is done positioning and multiplier crossed threshold.
        if (
            mult >= HARD_DROP_THRESHOLD
            and game.piece is not None
            and not action_queue
            and current_plan is not None
            and (sim_ms - last_slam_ms) >= SLAM_COOLDOWN_MS
        ):
            last_slam_ms = sim_ms
            game.hard_drop()

        # Lock-delay countdown.
        game.tick(int(dt * mult))

        # Drain events.
        for evt in game.drain_events():
            if isinstance(evt, TopOutEvent):
                deaths += 1
                current_plan = None
                action_queue = []
                last_planned = None
                continue
            if isinstance(evt, ClearEvent):
                # Record what we planned vs what happened.
                planned_tspin = ''
                planned_hold = False
                if last_planned is not None:
                    planned_tspin = last_planned.tspin_kind if last_planned.is_tspin else ''
                    planned_hold = last_planned.use_hold
                records.append((
                    evt.piece_kind,
                    planned_tspin,
                    planned_hold,
                    evt.t_spin,
                    len(evt.rows),
                ))
                pieces_processed += 1
                if verbose and planned_tspin and planned_tspin != evt.t_spin:
                    print(f"  MISMATCH seed={seed} piece#{pieces_processed}: "
                          f"planned={planned_tspin} actual={evt.t_spin or 'none'} "
                          f"lines={len(evt.rows)} kind={evt.piece_kind}")
                # Reset for next piece.
                current_plan = None
                action_queue = []
                last_planned = None

        sim_ms += dt

    return records, deaths


def summarize(label: str, all_records: list, total_games: int, total_deaths: int = 0):
    pieces = len(all_records)
    full_planned = sum(1 for r in all_records if r[1] == 'full')
    mini_planned = sum(1 for r in all_records if r[1] == 'mini')
    full_actual = sum(1 for r in all_records if r[3] == 'full')
    mini_actual = sum(1 for r in all_records if r[3] == 'mini')
    full_planned_actual_full = sum(1 for r in all_records if r[1] == 'full' and r[3] == 'full')
    mini_planned_actual_mini = sum(1 for r in all_records if r[1] == 'mini' and r[3] == 'mini')
    full_planned_no_spin = sum(1 for r in all_records if r[1] == 'full' and r[3] == '')
    mini_planned_no_spin = sum(1 for r in all_records if r[1] == 'mini' and r[3] == '')
    line_clears = sum(1 for r in all_records if r[4] > 0)

    def pct(num, denom):
        return f"{100*num/denom:.1f}%" if denom else "—"

    deaths_per_100 = (100 * total_deaths / pieces) if pieces else 0.0
    print(f"\n=== {label} ===")
    print(f"  games:                  {total_games}")
    print(f"  pieces locked:          {pieces}")
    print(f"  top-outs:               {total_deaths} ({deaths_per_100:.1f} per 100 pieces)")
    print(f"  line clears:            {line_clears}")
    print(f"  T-spin plans (full):    {full_planned}")
    print(f"  T-spin plans (mini):    {mini_planned}")
    print(f"  T-spin actual (full):   {full_actual}")
    print(f"  T-spin actual (mini):   {mini_actual}")
    print(f"  full plan → fired:      {full_planned_actual_full}/{full_planned} ({pct(full_planned_actual_full, full_planned)})")
    print(f"  mini plan → fired:      {mini_planned_actual_mini}/{mini_planned} ({pct(mini_planned_actual_mini, mini_planned)})")
    print(f"  full plan → no spin:    {full_planned_no_spin}  <- the failure mode")
    print(f"  mini plan → no spin:    {mini_planned_no_spin}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--games', type=int, default=5)
    ap.add_argument('--pieces', type=int, default=200, help='max pieces per game')
    ap.add_argument('--mode', default='tspin', choices=['calm', 'tetris', 'tspin'])
    ap.add_argument('--multiplier', type=float, default=1.0, help='typing multiplier (1.0 = idle)')
    ap.add_argument('--seeds', type=int, nargs='*', help='specific seeds (default: 0..games-1)')
    ap.add_argument('--verbose', action='store_true', help='print every plan-vs-actual mismatch')
    args = ap.parse_args()

    seeds = args.seeds if args.seeds else list(range(args.games))

    print(f"mode={args.mode} multiplier={args.multiplier} pieces/game={args.pieces} games={len(seeds)}")
    t0 = time.perf_counter()
    all_records = []
    total_deaths = 0
    for s in seeds:
        recs, d = run_game(s, args.mode, args.pieces, args.multiplier, args.verbose)
        all_records.extend(recs)
        total_deaths += d
    elapsed = time.perf_counter() - t0
    print(f"  ran in {elapsed:.1f}s ({len(all_records)/max(elapsed,1e-9):.0f} pieces/s)")

    summarize(f"mult={args.multiplier}", all_records, len(seeds), total_deaths)


if __name__ == '__main__':
    main()
