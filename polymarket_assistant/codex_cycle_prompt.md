<<CODEX_AUTO_CYCLE_V1>>
mode=decision_only
run_id={{RUN_ID}}
context_file={{CONTEXT_FILE}}
decision_file={{DECISION_FILE}}

This is an automated cycle trigger from the server, not a human chat message.

Read these inputs:
- polymarket_assistant/PLAYBOOK.md
- {{CONTEXT_FILE}}

Your job is only to decide whether to open, close, reduce, or skip.
Write exactly one JSON decision to {{DECISION_FILE}}.

Rules:
- Use the same JSON schema expected by polymarket_assistant/run_cycle.py --decision-file
- Include top-level "run_id": "{{RUN_ID}}"
- Do not ask follow-up questions
- Do not modify repo-tracked files
- Do not execute trading scripts
- If there is no valid edge, write NO_ACTION

After writing the JSON file, reply in chat with exactly:
AUTO_CYCLE_DONE {{RUN_ID}}
