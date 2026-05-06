# Codex Auto-Cycle Instructions

When you receive a prompt in this format:

`[auto-cycle-cli run_id=... instructions_md=... context_file=... decision_file=...]`

treat it as an automated Polymarket decision cycle.

Required steps:
1. Read this file.
2. Read `doc/polymarket_assistant/PLAYBOOK.md`.
3. Read `TIP.md` for situational notes that also apply to the current cycle.
4. Read `doc/polymarket_assistant/copilot_prompt.md` for the exact decision schema and slot rules.
5. Read the `context_file` path from the trigger line.
6. Reply with exactly one JSON decision and nothing else. The wrapper saves your final response to the `decision_file` path from the trigger line.
7. Use the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`, including `new_positions` and `position_managements` arrays.
8. Include the top-level `run_id` from the trigger line.
9. Do not ask follow-up questions.
10. Do not modify repo-tracked files.
11. Do not execute trading scripts.
12. If there is no valid edge, reply `NO_ACTION`.

Important schema reminders:
- `action` stays one of `NO_ACTION`, `OPEN_POSITION`, `CLOSE_POSITION`, or `REDUCE_POSITION`.
- `OPEN_POSITION` may include at most 1 item in `new_positions`, and it must be a daily market.
- `CLOSE_POSITION` and `REDUCE_POSITION` may include up to 2 items in `position_managements`, but do not mix CLOSE and REDUCE in the same response.
- Use empty arrays for the side that is not being used in the current decision.
- For every `OPEN_POSITION`, include `market_type`, `slot_name`, `beecthor_aligned`, `momentum_confirmed`, and `expiry_validity`.
- Do not open weekly positions. Existing weekly positions may be managed by exit logic, but new weekly exposure is disabled.
- Never use `expiry_validity: "weak"` for an opening. A correct level with poor expiry timing is still `NO_ACTION`.
- Correct for Beecthor's persistent bearish bias: if recent summaries are bearish but BTC is flat or net higher, require Binance rejection evidence before opening a bearish DIP.
- Treat discarded live positions as real account pain even when they no longer block slot availability.
- Do not chase after a large 24h BTC move unless the live probability and expiry validity are both strong.
