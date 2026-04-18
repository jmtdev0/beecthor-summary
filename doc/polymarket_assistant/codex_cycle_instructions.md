# Codex Auto-Cycle Instructions

When you receive a one-line prompt in this format:

`[auto-cycle run_id=... instructions_md=... context_file=... decision_file=...]`

treat it as an automated Polymarket decision cycle.

Required steps:
1. Read this file.
2. Read `doc/polymarket_assistant/PLAYBOOK.md`.
3. Read the `context_file` path from the trigger line.
4. Write exactly one JSON decision to the `decision_file` path from the trigger line.
5. Use the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`.
6. Include the top-level `run_id` from the trigger line.
7. Do not ask follow-up questions.
8. Do not modify repo-tracked files.
9. Do not execute trading scripts.
10. If there is no valid edge, write `NO_ACTION`.
11. After writing the file, reply in chat with exactly `AUTO_CYCLE_DONE <run_id>`.
