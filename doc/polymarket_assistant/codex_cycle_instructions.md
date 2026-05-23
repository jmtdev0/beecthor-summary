# Codex Auto-Cycle Instructions

When you receive a prompt in this format:

`[auto-cycle-cli run_id=... instructions_md=... context_file=... decision_file=...]`

treat it as an automated Polymarket decision cycle.

Required steps:
1. Read this file.
2. Read `doc/polymarket_assistant/PLAYBOOK.md`.
3. Read `TIP.md` for situational notes that also apply to the current cycle.
4. Read `doc/polymarket_assistant/copilot_prompt.md` for the exact decision schema and slot rules.
5. If active strategy is `far_dip_radar`, read `doc/polymarket_assistant/PLAYBOOK_FBR.md` as non-binding qualitative review guidance.
6. Read the `context_file` path from the trigger line.
7. Reply with exactly one JSON decision and nothing else. The wrapper saves your final response to the `decision_file` path from the trigger line.
8. Use the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`, including `new_positions` and `position_managements` arrays.
9. Include the top-level `run_id` from the trigger line.
10. Do not ask follow-up questions.
11. Do not modify repo-tracked files.
12. Do not execute trading scripts.
13. If there is no valid edge, reply `NO_ACTION`.

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
- Treat account liquidity/equity versus starting bankroll as informational only. Do not use low cash/equity as a reason to skip or lower confidence, except for hard stake funding and stake/slot caps.
- Do not chase after a large 24h BTC move unless the live probability and expiry validity are both strong.
- Your strategic decision is authoritative once emitted. The server validator should only enforce mechanical execution constraints, so do not rely on a later soft-validation pass to correct the decision.
- Read `context.strategy_state.active_strategy` from the context file before deciding.
- If active strategy is `beecthor-simulation`, use the latest synthetic Beecthor simulation in the context as the current thesis and make that explicit in the rationale.
- If active strategy is `far_dip_radar`, only choose a generated candidate from `context.strategy_context.far_dip_radar.candidates` or return `NO_ACTION`.
- For `far_dip_radar`, treat `PLAYBOOK_FBR.md` as a soft review checklist, not as a hard rulebook.
- For `far_dip_radar`, include the candidate metadata in `new_positions[0]` and discuss weekly BTC volatility in `rationale`.
