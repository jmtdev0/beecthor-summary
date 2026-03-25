# GitHub secrets for the Polymarket operator workflow

Create these repository secrets before enabling the workflow:

- `COPILOT_GITHUB_TOKEN`
  - Personal access token used by `copilot -p` in GitHub Actions.
- `POLY_SIGNER_ADDRESS`
- `POLY_FUNDER`
- `POLY_SIGNATURE_TYPE`
- `POLY_PRIVATE_KEY`
- `POLY_API_KEY`
- `POLY_API_SECRET`
- `POLY_API_PASSPHRASE`

Recommended workflow variables:

- `POLY_COPILOT_MODEL`
  - default: `gpt-5.4`

Notes:
- Do not store these values in tracked files.
- The workflow only stages `account_state.json`, `trade_log.json`, `last_run_summary.json`, and `last_run_summary.md`.
- `POLY_SIGNATURE_TYPE=1` is the correct value for the current Gmail-backed account flow discovered in local testing.
