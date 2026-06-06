"""
Generates a structured document-level summary during ingestion.

One LLM call per contract, result stored in Blob / local disk.
At query time the summary is returned directly — no retrieval needed.
"""

import json
import logging
import re
from typing import Dict

from openai import AzureOpenAI

from app import config

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a contract analyst. Given a portion of a contract document,
produce a structured JSON summary with exactly these fields:

{
  "purpose": "<1-2 sentences describing what the contract is for>",
  "parties": ["<Party A>", "<Party B>", ...],
  "effectiveDate": "<date or 'Not specified'>",
  "term": "<duration or expiry or 'Not specified'>",
  "keyObligations": ["<obligation 1>", "<obligation 2>", ...],
  "paymentSummary": "<brief description or 'Not specified'>",
  "terminationSummary": "<brief description or 'Not specified'>",
  "complianceTopics": ["<topic 1>", "<topic 2>", ...]
}

Output ONLY valid JSON — no markdown fences, no extra text.
Keep each field concise. keyObligations: max 6 items. complianceTopics: max 5 items."""

# Characters of raw text fed to the LLM (~4000 tokens at 4 chars/token)
_MAX_CHARS = 16_000


def generate_summary(contract_id: str, raw_text: str) -> Dict:
    """
    Call the LLM once to produce a structured summary dict.
    Falls back to a minimal placeholder if the call fails.
    """
    excerpt = raw_text[:_MAX_CHARS]

    client = AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )

    try:
        response = client.chat.completions.create(
            model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
            temperature=0,
            max_tokens=600,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": f"Contract excerpt:\n\n{excerpt}"},
            ],
        )
        raw = response.choices[0].message.content or ""
        cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
        summary = json.loads(cleaned)
        summary["contractId"] = contract_id
        logger.info("Generated summary for '%s'.", contract_id)
        return summary
    except Exception as exc:
        logger.warning("Summary generation failed for '%s': %s", contract_id, exc)
        return {
            "contractId": contract_id,
            "purpose": "Summary not available.",
            "parties": [],
            "effectiveDate": "Not specified",
            "term": "Not specified",
            "keyObligations": [],
            "paymentSummary": "Not specified",
            "terminationSummary": "Not specified",
            "complianceTopics": [],
        }


def format_summary_as_answer(summary: Dict) -> str:
    """
    Convert the stored summary dict into a readable answer string
    returned directly to the user — no LLM call needed at query time.
    """
    parties = ", ".join(summary.get("parties") or []) or "Not specified"
    obligations = summary.get("keyObligations") or []
    compliance = summary.get("complianceTopics") or []

    lines = [
        f"**Purpose:** {summary.get('purpose', 'Not specified')}",
        "",
        f"**Parties:** {parties}",
        f"**Effective Date:** {summary.get('effectiveDate', 'Not specified')}",
        f"**Term:** {summary.get('term', 'Not specified')}",
    ]

    if obligations:
        lines += ["", "**Key Obligations:**"]
        lines += [f"- {o}" for o in obligations]

    if summary.get("paymentSummary") and summary["paymentSummary"] != "Not specified":
        lines += ["", f"**Payment Structure:** {summary['paymentSummary']}"]

    if summary.get("terminationSummary") and summary["terminationSummary"] != "Not specified":
        lines += ["", f"**Termination:** {summary['terminationSummary']}"]

    if compliance:
        lines += ["", f"**Compliance Topics:** {', '.join(compliance)}"]

    return "\n".join(lines)
