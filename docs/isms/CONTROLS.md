# ISMS controls

Generated from `config/controls.yml`. `tests/test_isms.py` fails if any evidence is missing.

| Control | What the platform does | Evidence |
|---|---|---|
| **A.5.15** Access control | Roles in config/rbac.yml decide which tool a principal may call; every call goes through one gateway. | `tests/test_governance.py::test_a_role_cannot_call_tools_outside_it`<br>`config/rbac.yml` |
| **A.5.18** Access rights | API keys map to a subject, a role and a tenant; keys are stored as SHA-256 hashes and come from Key Vault. | `tests/test_api.py::test_unknown_keys_are_refused`<br>`infra/terraform/keyvault.tf` |
| **A.8.3** Information access restriction | The tenant comes from the caller's key, never from a tool argument; cross-tenant calls are denied and logged. | `tests/test_governance.py::test_the_tenant_comes_from_the_caller_not_the_arguments`<br>`tests/test_api.py::test_a_customer_sees_its_own_emissions_and_not_another_tenants` |
| **A.5.3** Segregation of duties | An approval must come from a person other than the requester, with a role that may approve. | `tests/test_governance.py::test_the_requester_cannot_approve_their_own_request`<br>`tests/test_governance.py::test_external_email_waits_for_a_person_who_is_not_the_requester` |
| **A.8.15** Logging | Every tool call, denial, queue entry and decision is appended to a hash-chained audit log persisted to PostgreSQL. | `tests/test_governance.py::test_the_audit_chain_detects_a_changed_entry`<br>`tests/test_api.py::test_the_audit_is_for_admins_and_verifies` |
| **A.8.16** Monitoring activities | OpenTelemetry spans and OpenMetrics go to Datadog; monitors page on denials, cost, latency and the quality CUSUM. | `deploy/datadog/monitors.yml`<br>`infra/terraform/datadog.tf`<br>`tests/test_monitor.py::test_no_alarm_at_the_baseline_rate_and_an_alarm_after_a_rise` |
| **A.8.25** Secure development life cycle | Every change runs lint, types, tests, the eval gate and the study's gates in CI before it can merge. | `.github/workflows/ci.yml`<br>`tests/test_lab.py::test_gates_read_the_designs` |
| **A.8.28** Secure coding | Untrusted text (files, replies, questions) is fenced; instructions in it are detected; it can never reach a write tool. | `tests/test_checks.py::test_the_fence_cannot_be_closed_from_inside`<br>`tests/test_checks.py::test_instructions_in_replies_are_noticed` |
| **A.8.29** Security testing in development and acceptance | The study runs a red-team set (injected replies, cross-tenant questions, write attempts) on every change. | `tests/test_platform.py::test_cross_tenant_questions_are_refused_and_writes_blocked`<br>`src/eap/evals/suite.py` |
| **A.8.32** Change management | A model or prompt change takes a router slot only after the eval gate passes; the held-out run happens once. | `src/eap/evals/suite.py`<br>`tests/test_lab.py::test_the_held_out_run_refuses_to_run_twice`<br>`docs/adr/0005-eval-gate.md` |
| **A.8.9** Configuration management | Infrastructure is Terraform; settings live in config/ by owner; reports are generated and CI fails on a diff. | `infra/terraform/main.tf`<br>`config/platform.yml` |
| **A.8.24** Use of cryptography | TLS to every endpoint, PostgreSQL with enforced TLS, Key Vault for secrets, storage encrypted at rest. | `infra/terraform/database.tf`<br>`infra/terraform/keyvault.tf` |
| **A.5.23** Information security for use of cloud services | Azure resources in one resource group per environment, private networking for the database, managed identities, no keys in code. | `infra/terraform/main.tf`<br>`infra/terraform/network.tf` |
| **A.8.12** Data leakage prevention | Carrier emails go to the registry's address only, drop unknown shipment ids and wait for a person; the mapping memory keys on header names, never row values. | `src/eap/platform/orchestrator.py`<br>`src/eap/platform/profile.py` |
