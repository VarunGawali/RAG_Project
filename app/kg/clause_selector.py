from typing import List
from app import config
from app.kg.models import KGNode


PRIORITY_KEYWORDS = [
    "shall",
    "must",
    "will",
    "notify",
    "submit",
    "provide",
    "deliver",
    "terminate",
    "termination",
    "liability",
    "indemnify",
    "indemnification",
    "confidential",
    "payment",
    "invoice",
    "report",
    "release",
    "approval",
    "consent",
    "within",
    "annually",
    "monthly",
    "deadline",
    "obligation",
    "responsible",
    "required",
]


HIGH_VALUE_CLAUSE_TYPES = {
    "termination",
    "payment",
    "liability",
    "indemnity",
    "confidentiality",
    "notice",
    "reporting_obligation",
    "maintenance",
    "environmental",
    "governing_law",
    "assignment",
    "audit",
    "insurance",
}


def score_clause(node: KGNode) -> int:
    text = f"{node.title or ''} {node.text or ''}".lower()
    score = 0

    for keyword in PRIORITY_KEYWORDS:
        if keyword in text:
            score += 3

    if node.clauseTypeHint in HIGH_VALUE_CLAUSE_TYPES:
        score += 8

    if node.pageStart is not None:
        score += 1

    text_len = len(node.text or "")

    if config.KG_MIN_CLAUSE_CHARS <= text_len <= config.KG_MAX_CLAUSE_CHARS:
        score += 5

    if node.label == "Clause":
        score += 10

    if node.label == "Section":
        score -= 5

    return score


def select_representative_clauses(
    nodes: List[KGNode],
    limit: int = 20,
) -> List[KGNode]:
    candidates = []

    for node in nodes:
        if node.label != "Clause":
            continue

        if not node.text or len(node.text.strip()) < config.KG_MIN_CLAUSE_CHARS:
            continue

        candidates.append(node)

    ranked = sorted(candidates, key=score_clause, reverse=True)

    return ranked[:limit]