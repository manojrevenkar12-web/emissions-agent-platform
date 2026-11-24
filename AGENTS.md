# Working on this repository

## Fast feedback

- `pytest -q` runs in under 10 s: a tiny simulated world, the local model, in-memory SQLite.
- `ruff check . && ruff format --check . && mypy src` for lint and types.
- `python -m eap.cli run dev && python -m eap.cli gate dev && python -m eap.cli report` runs every design on the
  development seeds (about 3 minutes on 3 cores) and regenerates REPORT.md, the README block, the console data and
  the ISMS control list.
- `cd web && npm test && npm run typecheck && npm run lint` for the console.
- `terraform -chdir=infra/terraform fmt -check -recursive` before touching infrastructure.

## Invariants

Each one has a test or a CI step.

- **The truth stays in the world.**
  - What designs get: carrier files as a CSV would show them, the model's answers, carrier replies, people's answers.
  - What only the evaluation (`sim/evaluate.py`) and the golden set (`evals/suite.py`) may read: a file's true
    fields, units, modes, distances and fuel.
  - Test: `tests/test_boundaries.py`.
- **The world does not read the platform's settings.**
  - `world/` loads `world.yml` only. `platform/`, `service/` and `agents/` never import `world` or `sim`.
  - Test: `tests/test_boundaries.py`.
- **Same luck for every design.** Every coin is keyed by (seed, purpose, id) in `world/luck.py`; a case's coin is
  shared by every model, so a stronger model is right wherever a weaker one is. Test: `tests/test_same_luck.py`.
- **The model reads and code decides.** A reading counts only as a typed `Mapping`; `platform/checks.py` decides what
  it implies; the calculation (`platform/calc.py`), deduplication and data-quality labels are code; an answer's number
  must be the tool's number. Tests: `tests/test_checks.py`, `tests/test_calc.py`.
- **Customer and carrier text is data.** Files, replies and questions are fenced in prompts; text that reads like an
  instruction goes to a person; no reply or question can reach a write tool.
- **One gateway for every tool call.** Roles from `config/rbac.yml`; the tenant comes from the caller's identity;
  external and overriding tools wait for a person other than the requester; every call is in the hash-chained audit.
  Tests: `tests/test_governance.py`, `tests/test_api.py`, `tests/test_mcp.py`.
- **A model change passes the eval gate first** (`evals/suite.py`, ADR 0005).
- **Settings live in `config/`**, by owner: the world in `world.yml`; the platform in `platform.yml`; roles in
  `rbac.yml`; designs in `designs.yml`; seeds in `seeds.yml`; thresholds in `gates.yml`; ISMS evidence in
  `controls.yml`.
- **Reports are generated, never edited.** CI regenerates REPORT.md, the README block, `web/public/data/report.json`
  and `docs/isms/CONTROLS.md` and fails on a diff.

## Held-out seeds

- `config/seeds.yml` lists them; they run in the held-out world (`world.yml: heldout`): new header languages, inland
  waterway, more unit changes, more injected replies, a longer provider regression.
- `python -m eap.cli run heldout` writes `reports/heldout.lock` before it runs. If the lock exists it exits with
  code 3. CI checks the lock was committed exactly once.
- Gates were set from the development seeds before the held-out run. Never loosen a gate after it.
- If a change needs new held-out evidence, add new seeds under a new name and record why in an ADR.

## Data

Everything is simulated. Company names are invented; locations are public reference data.
