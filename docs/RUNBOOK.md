# Runbook

Every Datadog monitor links to a section here (`deploy/datadog/monitors.yml`).

## model-cost-above-budget
1. In Datadog, group `eap.llm_cost_eur` by `span`. A jump in `map.read` and `map.second_read` with flat file volume
   usually means the mapping memory stopped hitting: check `map.memory` spans with `drift` set.
2. A jump in `email.draft` means many carriers crossed `clarification.min_shipments` at once (month end); expected.
3. If a loop is suspected, set `routing.first` and `routing.escalate` to `local` in config and redeploy: the desk
   keeps working on the local model and people review more.

## denied-tool-calls
1. `GET /v1/audit` with an admin key; filter entries with outcome `denied` and read `detail.reason`.
2. `cross-tenant` from one customer key: contact the customer; their integration is asking for another tenant.
3. `role ... may not call` from an agent principal: a prompt or model change is calling a tool outside its role. Roll
   back the change; the eval gate should have caught it.

## quality-alarm
1. The router has already pinned first reads to the escalation model for ten days; nothing has to be done to stop
   bad data, but people's review queue grows.
2. Check the model provider's status page. Run `python -m eap.cli evals` against the current model to confirm.
3. When the provider fixes it, the pin expires by itself. If it does not recover, move `routing.first` to the next
   model that passes the eval gate.

## slow-model-calls
1. Compare p95 of `map.read` by `gen_ai.request.model`. Provider latency: nothing to fix locally.
2. Large prompts: `eap.profile_tokens` above the budget means `profile.token_budget` was raised.

## approvals-waiting
1. `GET /v1/approvals` with an analyst key. Month end produces a burst of carrier emails.
2. Approve in batches; an approval needs a person other than the requester (separation of duties).

## Restore the database
Azure Database for PostgreSQL keeps point-in-time backups (7 days, 35 in prod). Restore to a new server, point
`database-url` in Key Vault at it, restart the Container App revision. The audit chain verifies after restore
(`GET /v1/audit` returns `verified: true`).
