# Repeatable tasks

## Add a check
1. Write the check in `src/eap/platform/checks.py`; it must name the decisions it rejects (`col:`, `unit:`, `code:`).
2. Put its thresholds in `config/platform.yml` under `checks`.
3. Add a test in `tests/test_checks.py` that a true reading passes and the wrong reading fails.
4. `python -m eap.cli run dev`, look at `gross_row_errors_per_10k` and analyst minutes, then `report`.

## Try a new model or prompt
1. Add the model to `world.yml: models` (simulation) and `platform.yml: prices_eur_per_mtok` and `claude_models`.
2. Add it under `designs.yml: model_swap` with the slot it replaces.
3. `python -m eap.cli evals` prints the gate's verdict; `run dev` shows what it does in the world.
4. Only a candidate that passes the gate takes the slot in `platform.yml: routing`.

## Give an agent a new tool
1. Register it in `Platform._register_tools` with a JSON schema and a risk (read, write, external).
2. Add it to the narrowest role in `config/rbac.yml`; add it to `approvals.required_for` if it leaves the company or
   overrides data.
3. If the MCP server should expose it, add it in `src/eap/agents/mcp_server.py`.
4. Test the denial path in `tests/test_governance.py`.

## Run the service locally
`python -m eap.cli serve` (local model, demo data, in-memory store), then for example
`curl -H "Authorization: Bearer demo-viewer-t1" "localhost:8000/v1/emissions?month=0"`.
With `EAP_MODEL=claude` and `ANTHROPIC_API_KEY` set, the agents call Claude instead.

## Connect Claude Code or Claude Desktop over MCP
`EAP_API_KEY=demo-analyst-anna python -m eap.cli mcp` serves the platform's tools over stdio with that key's rights.

## Deploy
`terraform -chdir=infra/terraform init -backend-config=env/<env>.backend.hcl`, then
`terraform -chdir=infra/terraform apply -var env=<env> -var image_tag=<sha> ...`. See docs/RUNBOOK.md.

## Regenerate the demo data and screenshots
`python scripts/make_demo_data.py`; `cd web && npm run build && cd .. && python scripts/screenshots.py`.

## Run the held-out world
Only once, after the gates are set: `python -m eap.cli run heldout && python -m eap.cli report`.
