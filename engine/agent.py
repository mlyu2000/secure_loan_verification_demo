"""Memo drafting by the agent (the generative AI step).

Design (robust + faithful to the video's "agent pulls data and drafts the memo"):
  - The ENGINE drives the governed MCP data calls (CRM/credit/transactions/compliance/
    prior-memo + submit) — that is the governance + data path (steps 3-7, 9).
  - The AGENT (LLM or deterministic stub) DRAFTS the memo from the collected data —
    that is the visible AI step (step 8).

Backends:
  - stub        deterministic memo from fixtures (simulation / no-LLM).
  - direct_llm  LLM (litellm) writes the memo from the collected data; validated.
  - openclaw    (reserved) full OpenClaw tool-calling agent, enabled at M2.
"""
from __future__ import annotations

import json
import logging

import httpx

from .config import settings
from .memo import build_stub_memo, validate_memo
from .security import Identity

log = logging.getLogger("slvd.agent")

DRAFT_PROMPT = """You are credit-memo-agent, a governed credit-risk analyst. Below is data
collected from the bank's systems for a loan renewal case. Draft the renewal decision memo.

Required output format (markdown), exactly these sections:
# Loan Renewal Decision Memo
A line with the client name and client code, e.g. "Client: <name> (<code>) — Renewal Request"
## Overview
- Requested renewal amount: <the requested amount, dollars, comma-formatted>
- Current utilization: <utilization dollars> (<pct>% of limit)
- Facility type: <facility>
- Risk rating: <rating>
- Status: <covenant status>
## Key Considerations
At least 3 numbered points drawn from the data (transaction history, KYC status,
prior-memo conditions, open follow-ups).
## Recommended Decision
One or two sentences: the recommended decision (Approve / Approve with conditions / Decline)
and the key conditions or rationale.

Rules:
- Use ONLY the values in the provided data. Never invent numbers or facts.
- The "Requested renewal amount" is the amount the analyst requested (given below), NOT the
  facility limit.
- Be concise and professional, like a bank credit memo.

Requested case:
{case_block}

Collected data (JSON):
{data_block}
"""


class AgentResult:
    def __init__(self, memo_md: str, ok: bool, notes: str = ""):
        self.memo_md = memo_md
        self.ok = ok
        self.notes = notes


def draft_stub(case: dict, requested_amount_usd: int) -> AgentResult:
    return AgentResult(build_stub_memo(case, requested_amount_usd), True, "stub-agent")


def _case_block(case: dict, requested_amount_usd: int) -> str:
    return (f"case_id={case['case_id']}, client={case['client']}, "
            f"client_code={case['client_code']}, "
            f"requested_renewal_amount=${requested_amount_usd:,} USD")


def _data_block(data: dict) -> str:
    return json.dumps(data, indent=2)


def draft_llm(case: dict, data: dict, requested_amount_usd: int) -> AgentResult:
    """Ask the LLM to draft the memo from collected data; validate; one re-prompt."""
    prompt = DRAFT_PROMPT.format(case_block=_case_block(case, requested_amount_usd),
                                 data_block=_data_block(data))
    messages = [
        {"role": "system", "content":
         "You are a precise bank credit-risk analyst. Output only the markdown memo."},
        {"role": "user", "content": prompt},
    ]
    memo = _chat(messages)
    if not memo:
        log.warning("LLM returned empty memo; falling back to stub")
        return AgentResult(build_stub_memo(case, requested_amount_usd), True,
                           "llm-empty-fallback-stub")
    check = validate_memo(memo, case, requested_amount_usd)
    if not check.ok:
        messages.append({"role": "user", "content":
                         f"Your memo is missing required content: {', '.join(check.missing)}. "
                         "Return the complete corrected memo now (markdown only)."})
        retry = _chat(messages)
        if retry:
            memo = retry
            check = validate_memo(memo, case, requested_amount_usd)
    if not check.ok:
        return AgentResult(memo, False, f"memo-invalid:{','.join(check.missing)}")
    return AgentResult(memo, True, "direct-llm")


def _chat(messages: list[dict]) -> str:
    r = httpx.post(
        f"{settings.llm_base_url}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={"model": settings.llm_model, "messages": messages, "max_tokens": 4096,
              "temperature": 0.2},
        timeout=settings.llm_timeout_s,
    )
    r.raise_for_status()
    content = r.json()["choices"][0]["message"].get("content")
    return (content or "").strip()


def draft_memo(case: dict, data: dict, requested_amount_usd: int) -> AgentResult:
    backend = settings.agent_backend
    if backend in ("stub", "sim"):
        return draft_stub(case, requested_amount_usd)
    if backend == "direct_llm":
        try:
            return draft_llm(case, data, requested_amount_usd)
        except Exception as e:  # noqa: BLE001
            log.error("direct_llm failed: %s — falling back to stub", e)
            return AgentResult(build_stub_memo(case, requested_amount_usd), True,
                               f"llm-error-fallback-stub:{type(e).__name__}")
    if backend == "openclaw":
        raise NotImplementedError("openclaw backend enabled at M2 (see plan §4.4)")
    raise ValueError(f"unknown agent backend: {backend}")
