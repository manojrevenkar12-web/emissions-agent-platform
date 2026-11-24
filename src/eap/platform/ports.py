"""What the platform needs from outside: a model, people and a mailbox. The simulation and the real service
plug different implementations into the same ports.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from ..domain import CarrierRecord, EmailDraft, FileView, Mapping, ModelReply, ParsedReply, Question, ToolCall


class ModelPort(Protocol):
    def propose_mapping(self, view: FileView, prompt: str, tier: str) -> ModelReply: ...

    def draft_email(self, record: CarrierRecord, shipment_ids: list[str], prompt: str, tier: str, ref: str) -> ModelReply: ...

    def parse_reply(self, text: str, prompt: str, tier: str, ref: str) -> ModelReply: ...

    def plan_query(self, question: Question, prompt: str, tier: str) -> ModelReply: ...

    def write_answer(self, question: Question, result: dict[str, float | str], prompt: str, tier: str, attempt: int) -> ModelReply: ...


class PeoplePort(Protocol):
    def review_mapping(self, view: FileView, proposal: Mapping, flagged: list[str]) -> Mapping: ...

    def map_by_hand(self, view: FileView, sheet: Mapping | None) -> Mapping: ...

    def review_rows(self, view: FileView, rows: np.ndarray, weight_t: np.ndarray) -> np.ndarray: ...

    def review_reply(self, ref: str, text: str, parsed: ParsedReply) -> ParsedReply: ...

    def review_email(self, draft: EmailDraft, valid_ids: set[str]) -> EmailDraft: ...


class MailPort(Protocol):
    def send(self, draft: EmailDraft, day: int, ref: str) -> None: ...


__all__ = ["ModelPort", "PeoplePort", "MailPort", "ToolCall"]
