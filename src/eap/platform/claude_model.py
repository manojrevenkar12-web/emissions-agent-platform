"""The hosted model behind the same port: Claude through the Messages API.

Tiers map to model ids in config/platform.yml (`claude_models`), so the router and the eval gate work on
tier names and a model change is a config change that has to pass the gate. Every answer must parse into
the platform's types; anything else raises and the orchestrator treats the read as failed.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from ..domain import CarrierRecord, EmailDraft, FileView, Mapping, ModelReply, ParsedReply, Question, ToolCall
from . import prompts


class ClaudeModel:
    def __init__(self, cfg: dict[str, Any], client: Any | None = None) -> None:
        if client is None:
            import anthropic  # optional dependency: pip install anthropic

            client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        self.client = client
        self.models: dict[str, str] = {k: os.environ.get(f"EAP_MODEL_{k.upper()}", v) for k, v in cfg["claude_models"].items()}

    def _ask(self, tier: str, system: str, user: str, max_tokens: int = 1200) -> tuple[str, int, int, float]:
        t0 = time.perf_counter()
        r = self.client.messages.create(model=self.models[tier], max_tokens=max_tokens, system=system, messages=[{"role": "user", "content": user}])
        text = "".join(getattr(b, "text", "") for b in r.content)
        return text, int(r.usage.input_tokens), int(r.usage.output_tokens), (time.perf_counter() - t0) * 1000

    @staticmethod
    def _json(text: str) -> Any:
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            raise ValueError("no JSON in the model's answer")
        return json.loads(m.group(0))

    def propose_mapping(self, view: FileView, prompt: str, tier: str) -> ModelReply:
        text, tin, tout, ms = self._ask(tier, prompts.MAPPING, prompt)
        m = Mapping.from_dict(self._json(text))
        return ModelReply(m, tier, tin, tout, ms)

    def draft_email(self, record: CarrierRecord, shipment_ids: list[str], prompt: str, tier: str, ref: str) -> ModelReply:
        user = f"Carrier: {record.name}\nShipment ids:\n" + "\n".join(shipment_ids)
        text, tin, tout, ms = self._ask(tier, prompt, user, 800)
        return ModelReply(EmailDraft(record.carrier_id, record.contact, "Fuel data per shipment", text, list(shipment_ids)), tier, tin, tout, ms)

    def parse_reply(self, text: str, prompt: str, tier: str, ref: str) -> ModelReply:
        out, tin, tout, ms = self._ask(tier, prompts.REPLY, prompt)
        d = self._json(out)
        unit = d.get("unit") if d.get("unit") in ("l", "gal") else None
        values = {str(k): float(v) for k, v in (d.get("values") or {}).items()}
        return ModelReply(ParsedReply(unit, values), tier, tin, tout, ms)

    def plan_query(self, question: Question, prompt: str, tier: str) -> ModelReply:
        system = prompts.QA + '\nReturn JSON only: {"metric": "total"|"by_mode"|"lane"|"primary_share", "month": 0-11, "mode": str|null, "origin": LOCODE|null, "destination": LOCODE|null}'
        out, tin, tout, ms = self._ask(tier, system, prompt, 300)
        d = self._json(out)
        args = {"tenant": question.tenant, **{k: v for k, v in d.items() if v is not None}}
        return ModelReply([ToolCall("query_emissions", args)], tier, tin, tout, ms)

    def write_answer(self, question: Question, result: dict[str, float | str], prompt: str, tier: str, attempt: int) -> ModelReply:
        out, tin, tout, ms = self._ask(tier, prompts.QA, f"{prompt}\nTool result: {json.dumps(result)}\nAnswer in one sentence.", 200)
        return ModelReply(out.strip(), tier, tin, tout, ms)
