[auto-cycle-cli run_id={{RUN_ID}} instructions_md=/root/beecthor-summary/doc/polymarket_assistant/codex_cycle_instructions.md context_file={{CONTEXT_FILE}} decision_file={{DECISION_FILE}}]

You are running the automated Polymarket decision cycle in Codex CLI read-only mode.

Required steps:
1. Read `/root/beecthor-summary/doc/polymarket_assistant/codex_cycle_instructions.md`.
2. Read `/root/beecthor-summary/doc/polymarket_assistant/PLAYBOOK.md`.
3. Read `/root/beecthor-summary/TIP.md` if it exists.
4. Read `/root/beecthor-summary/doc/polymarket_assistant/copilot_prompt.md` for the exact decision schema and slot rules.
5. If active strategy is `far_dip_radar`, read `/root/beecthor-summary/doc/polymarket_assistant/PLAYBOOK_FBR.md` as non-binding qualitative review guidance. If active strategy is `beecthor-simulation`, use the latest synthetic Beecthor simulation from the context as the current thesis.
6. Read `{{CONTEXT_FILE}}`.
7. Do not modify files.
8. Do not execute trading scripts.
9. Reply with exactly one valid JSON object and nothing else. The wrapper will save your final response to `{{DECISION_FILE}}`.
10. Include top-level `run_id` exactly: `{{RUN_ID}}`.
11. Use the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`, including `new_positions` and `position_managements` arrays.
12. If there is no valid edge, reply `NO_ACTION`.
