# Codex Auto-Cycle Instructions

When you receive a one-line prompt in this format:

`[auto-cycle run_id=... instructions_md=... context_file=... decision_file=...]`

treat it as an automated Polymarket decision cycle.

Required steps:
1. Read this file.
2. Read `doc/polymarket_assistant/PLAYBOOK.md`.
3. Read `doc/polymarket_assistant/copilot_prompt.md` for the exact decision schema and slot rules.
4. Read the `context_file` path from the trigger line.
5. Write exactly one JSON decision to the `decision_file` path from the trigger line.
6. Use the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`, including `new_positions` and `position_managements` arrays.
7. Include the top-level `run_id` from the trigger line.
8. Do not ask follow-up questions.
9. Do not modify repo-tracked files.
10. Do not execute trading scripts.
11. If there is no valid edge, write `NO_ACTION`.
12. After writing the file, reply in chat with exactly `AUTO_CYCLE_DONE <run_id>`.

Important schema reminders:
- `action` stays one of `NO_ACTION`, `OPEN_POSITION`, `CLOSE_POSITION`, or `REDUCE_POSITION`.
- `OPEN_POSITION` may include up to 2 items in `new_positions` when different free slots are independently valid.
- `CLOSE_POSITION` and `REDUCE_POSITION` may include up to 2 items in `position_managements`, but do not mix CLOSE and REDUCE in the same response.
- Use empty arrays for the side that is not being used in the current decision.
