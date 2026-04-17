[auto-cycle run_id={{RUN_ID}} context_file={{CONTEXT_FILE}} decision_file={{DECISION_FILE}}]

Read `polymarket_assistant/PLAYBOOK.md` and `{{CONTEXT_FILE}}`.

Write exactly one JSON decision to `{{DECISION_FILE}}` using the schema expected by `polymarket_assistant/run_cycle_codex.py --decision-file`.
Include top-level `"run_id": "{{RUN_ID}}"`.
Do not ask follow-up questions.
Do not modify repo-tracked files.
Do not execute trading scripts.
If there is no valid edge, write `NO_ACTION`.

After writing the file, reply in chat with exactly:
AUTO_CYCLE_DONE {{RUN_ID}}
