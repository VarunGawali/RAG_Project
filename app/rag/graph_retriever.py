"""
Graph-native retriever for Contract360.

Queries Cosmos Gremlin directly for structured semantic facts.
Supports:
  - Single-contract scoped queries  (contract_id set)
  - Multi-contract scoped queries   (contract_ids list)
  - Portfolio-wide queries          (no filter)
  - Cross-contract analysis         (shared parties, comparative obligations)

Route: "graph" — no Azure AI Search involved.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.kg.gremlin_writer import GremlinWriter

logger = logging.getLogger(__name__)


# ── Party alias normalisation ──────────────────────────────────────────────────

PARTY_ALIASES = {
    "con edison": "Con Edison",
    "consolidated edison": "Con Edison",
    "power authority": "Power Authority",
    "nypa": "Power Authority",
    "new york power authority": "Power Authority",
    "either party": "Either Party",
    "breaching party": "Breaching Party",
    "non-breaching party": "Non-Breaching Party",
}


# ── Gremlin helpers ────────────────────────────────────────────────────────────

def first_value(prop_map: Dict[str, Any], key: str, default=None):
    value = prop_map.get(key, default)
    if isinstance(value, list):
        return value[0] if value else default
    return value


def extract_party(question: str) -> Optional[str]:
    q = question.lower()
    for alias, canonical in PARTY_ALIASES.items():
        if alias in q:
            return canonical
    return None


def _contract_filter_step(contract_id: Optional[str], contract_ids: Optional[List[str]]) -> str:
    """Return a Gremlin has() filter fragment, or empty string for portfolio-wide."""
    if contract_ids and len(contract_ids) == 1:
        contract_id = contract_ids[0]
        contract_ids = None
    if contract_id and not contract_ids:
        return f".has('contractId', '{contract_id}')"
    # Multi-contract: Cosmos Gremlin doesn't support within(), use or()
    if contract_ids:
        clauses = ", ".join(f"has('contractId', '{cid}')" for cid in contract_ids)
        return f".or({clauses})"
    return ""  # portfolio-wide — no filter


def _filter_by_contracts(
    items: List[Dict],
    contract_id: Optional[str],
    contract_ids: Optional[List[str]],
) -> List[Dict]:
    """Post-query Python filter when Gremlin-side filter is not applied."""
    scope = set()
    if contract_id:
        scope.add(contract_id)
    if contract_ids:
        scope.update(contract_ids)
    if not scope:
        return items
    return [i for i in items if first_value(i, "contractId") in scope]


def normalize_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "kgId":          first_value(item, "kgId"),
            "name":          first_value(item, "name"),
            "contractId":    first_value(item, "contractId"),
            "confidence":    first_value(item, "confidence"),
            "evidenceQuote": first_value(item, "evidenceQuote"),
            "sourceClauseId": first_value(item, "sourceClauseId"),
        }
        for item in items
    ]


# ── GraphNativeRetriever ───────────────────────────────────────────────────────

class GraphNativeRetriever:
    def __init__(self):
        self.writer = GremlinWriter()

    def close(self):
        self.writer.close()

    # ── Per-contract queries ───────────────────────────────────────────

    def get_obligations_by_party(
        self,
        party_name: str,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Party').has('name', party_name){cf}
          .in('OWED_BY').hasLabel('Obligation').dedup()
          .valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        result = self.writer.submit(query, {"party_name": party_name})
        return normalize_items(result)

    def get_obligations_owed_to_party(
        self,
        party_name: str,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Party').has('name', party_name){cf}
          .in('OWED_TO').hasLabel('Obligation').dedup()
          .valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        result = self.writer.submit(query, {"party_name": party_name})
        return normalize_items(result)

    def get_obligations_with_deadlines(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Obligation'){cf}.as('obligation')
          .out('HAS_DEADLINE').hasLabel('Deadline').as('deadline')
          .select('obligation', 'deadline')
            .by(valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId'))
            .by(valueMap('kgId', 'name', 'evidenceQuote'))
        """
        result = self.writer.submit(query)
        items = []
        for row in result:
            o = row.get("obligation", {})
            d = row.get("deadline", {})
            cid = first_value(o, "contractId")
            items.append({
                "kgId":            first_value(o, "kgId"),
                "name":            first_value(o, "name"),
                "contractId":      cid,
                "confidence":      first_value(o, "confidence"),
                "evidenceQuote":   first_value(o, "evidenceQuote"),
                "sourceClauseId":  first_value(o, "sourceClauseId"),
                "deadlineName":    first_value(d, "name"),
                "deadlineEvidence": first_value(d, "evidenceQuote"),
            })
        return _filter_by_contracts(items, contract_id, contract_ids)

    def get_all_obligations(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Obligation'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    def get_rights(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Right'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    def get_restrictions(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Restriction'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    def get_clause_metadata(self, source_clause_id: str) -> Dict:
        query = """
        g.V(source_clause_id)
          .valueMap('kgId', 'contractId', 'title', 'pageStart', 'pageEnd', 'sourcePath', 'textPreview')
        """
        result = self.writer.submit(query, {"source_clause_id": source_clause_id})
        if not result:
            return {}
        row = result[0]
        return {
            "kgId":        first_value(row, "kgId"),
            "contractId":  first_value(row, "contractId"),
            "title":       first_value(row, "title"),
            "pageStart":   first_value(row, "pageStart"),
            "pageEnd":     first_value(row, "pageEnd"),
            "sourcePath":  first_value(row, "sourcePath"),
            "textPreview": first_value(row, "textPreview"),
        }

    # ── Cross-contract queries ─────────────────────────────────────────

    def get_shared_parties(self, contract_ids: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """
        Return parties that appear in more than one contract.
        { party_name: [contractId, contractId, ...] }
        """
        query = """
        g.V().hasLabel('Party').dedup()
          .valueMap('name', 'contractId')
        """
        result = self.writer.submit(query)
        party_contracts: Dict[str, List[str]] = defaultdict(list)
        for item in result:
            name = first_value(item, "name")
            cid  = first_value(item, "contractId")
            if name and cid:
                scope = set(contract_ids) if contract_ids else None
                if scope is None or cid in scope:
                    party_contracts[name].append(cid)
        # Keep only parties appearing in 2+ contracts
        return {
            name: sorted(set(cids))
            for name, cids in party_contracts.items()
            if len(set(cids)) > 1
        }

    def get_obligations_grouped_by_contract(
        self,
        contract_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        """Return all obligations grouped by contractId for comparison."""
        items = self.get_all_obligations(contract_ids=contract_ids)
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            cid = item.get("contractId") or "unknown"
            grouped[cid].append(item)
        return dict(grouped)

    def get_deadlines_grouped_by_contract(
        self,
        contract_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        """Return all deadline-bearing obligations grouped by contractId."""
        items = self.get_obligations_with_deadlines(contract_ids=contract_ids)
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            cid = item.get("contractId") or "unknown"
            grouped[cid].append(item)
        return dict(grouped)


# ── Formatting ─────────────────────────────────────────────────────────────────

def _format_facts(
    facts: List[Dict],
    retriever: GraphNativeRetriever,
    show_contract: bool = False,
) -> List[str]:
    lines = []
    for idx, fact in enumerate(facts, start=1):
        source_clause_id = fact.get("sourceClauseId")
        meta = retriever.get_clause_metadata(source_clause_id) if source_clause_id else {}
        lines.append(f"  {idx}. {fact.get('name')}")
        if show_contract and fact.get("contractId"):
            lines.append(f"     Contract: {fact.get('contractId')}")
        if fact.get("deadlineName"):
            lines.append(f"     Deadline: {fact.get('deadlineName')}")
        if fact.get("evidenceQuote"):
            lines.append(f"     Evidence: \"{fact.get('evidenceQuote')}\"")
        if meta:
            lines.append(
                f"     Source: {meta.get('title')} "
                f"(pp. {meta.get('pageStart')}-{meta.get('pageEnd')})"
            )
    return lines


def format_graph_result(
    question: str,
    intent: str,
    facts: List[Dict],
    retriever: GraphNativeRetriever,
    multi_contract: bool = False,
) -> str:
    header = ["=" * 80, "GRAPH RETRIEVAL", "=" * 80,
              f"Question: {question}", f"Intent: {intent}",
              f"Facts found: {len(facts)}", ""]
    if not facts:
        return "\n".join(header + ["No graph facts found for this query."])
    lines = header + _format_facts(facts, retriever, show_contract=multi_contract)
    return "\n".join(lines)


def format_cross_contract_result(
    question: str,
    intent: str,
    grouped: Dict[str, List[Dict]],
    retriever: GraphNativeRetriever,
    extra_sections: Optional[List[str]] = None,
) -> str:
    total = sum(len(v) for v in grouped.values())
    lines = [
        "=" * 80, "CROSS-CONTRACT GRAPH RETRIEVAL", "=" * 80,
        f"Question: {question}", f"Intent: {intent}",
        f"Contracts in scope: {len(grouped)}  |  Total facts: {total}", "",
    ]
    for contract_id, facts in sorted(grouped.items()):
        lines += [
            f"── {contract_id} ({len(facts)} facts) " + "─" * max(0, 60 - len(contract_id)),
        ]
        lines += _format_facts(facts, retriever, show_contract=False)
        lines.append("")
    if extra_sections:
        lines += extra_sections
    return "\n".join(lines)


# ── Main entry point ───────────────────────────────────────────────────────────

def graph_native_retrieve(
    question: str,
    contract_id: Optional[str] = None,
    contract_ids: Optional[List[str]] = None,
) -> str:
    """
    Route graph questions to the right Gremlin query pattern.
    Automatically chooses single-contract, multi-contract, or cross-contract
    analysis based on the active scope.
    """
    q = question.lower()

    # Resolve effective scope
    scope_ids: Optional[List[str]] = None
    if contract_ids:
        scope_ids = contract_ids
    elif contract_id:
        scope_ids = [contract_id]
    multi = scope_ids is not None and len(scope_ids) > 1
    portfolio = scope_ids is None

    retriever = GraphNativeRetriever()
    try:
        party = extract_party(question)

        # ── Deadline questions ─────────────────────────────────────────
        if "deadline" in q or "due" in q or "by when" in q:
            if multi or portfolio:
                grouped = retriever.get_deadlines_grouped_by_contract(
                    contract_ids=scope_ids,
                )
                return format_cross_contract_result(
                    question, "obligations_with_deadlines", grouped, retriever,
                )
            facts = retriever.get_obligations_with_deadlines(
                contract_id=contract_id, contract_ids=scope_ids,
            )
            return format_graph_result(question, "obligations_with_deadlines", facts, retriever)

        # ── Shared party / cross-contract questions ────────────────────
        cross_triggers = ["across contracts", "compare", "shared parties",
                          "both contracts", "all contracts", "portfolio", "multiple contracts"]
        if any(t in q for t in cross_triggers) or (portfolio and party is None):
            shared = retriever.get_shared_parties(contract_ids=scope_ids)
            grouped = retriever.get_obligations_grouped_by_contract(
                contract_ids=scope_ids,
            )
            extra = []
            if shared:
                extra.append("\n── Parties Appearing in Multiple Contracts ─────────────")
                for pname, cids in sorted(shared.items()):
                    extra.append(f"  {pname}: {', '.join(cids)}")
            return format_cross_contract_result(
                question, "cross_contract_analysis", grouped, retriever, extra_sections=extra,
            )

        # ── Party-owed-to questions ────────────────────────────────────
        if "owed to" in q and party:
            if multi or portfolio:
                grouped = defaultdict(list)
                for cid in (scope_ids or [None]):
                    facts = retriever.get_obligations_owed_to_party(
                        party, contract_id=cid if not multi else None,
                        contract_ids=scope_ids if multi else None,
                    )
                    for f in facts:
                        grouped[f.get("contractId", "unknown")].append(f)
                return format_cross_contract_result(
                    question, f"obligations_owed_to:{party}", dict(grouped), retriever,
                )
            facts = retriever.get_obligations_owed_to_party(
                party, contract_id=contract_id, contract_ids=scope_ids,
            )
            return format_graph_result(
                question, f"obligations_owed_to:{party}", facts, retriever,
            )

        # ── Party-obligation questions ─────────────────────────────────
        if ("obligation" in q or "responsible" in q or "owe" in q or "owed" in q) and party:
            if multi or portfolio:
                facts = retriever.get_obligations_by_party(
                    party, contract_ids=scope_ids,
                )
                grouped: Dict[str, List] = defaultdict(list)
                for f in facts:
                    grouped[f.get("contractId", "unknown")].append(f)
                return format_cross_contract_result(
                    question, f"obligations_by_party:{party}", dict(grouped), retriever,
                )
            facts = retriever.get_obligations_by_party(
                party, contract_id=contract_id, contract_ids=scope_ids,
            )
            return format_graph_result(
                question, f"obligations_by_party:{party}", facts, retriever,
            )

        # ── All obligations (no specific party) ────────────────────────
        if "obligation" in q or "responsible" in q:
            if multi or portfolio:
                grouped = retriever.get_obligations_grouped_by_contract(
                    contract_ids=scope_ids,
                )
                return format_cross_contract_result(
                    question, "all_obligations", grouped, retriever,
                )
            facts = retriever.get_all_obligations(
                contract_id=contract_id, contract_ids=scope_ids,
            )
            return format_graph_result(question, "all_obligations", facts, retriever)

        # ── Rights ────────────────────────────────────────────────────
        if "right" in q:
            facts = retriever.get_rights(
                contract_id=contract_id, contract_ids=scope_ids,
            )
            multi_ctx = multi or portfolio
            return format_graph_result(
                question, "rights", facts, retriever, multi_contract=multi_ctx,
            )

        # ── Restrictions ──────────────────────────────────────────────
        if "restriction" in q or "prohibit" in q or "shall not" in q:
            facts = retriever.get_restrictions(
                contract_id=contract_id, contract_ids=scope_ids,
            )
            multi_ctx = multi or portfolio
            return format_graph_result(
                question, "restrictions", facts, retriever, multi_contract=multi_ctx,
            )

        # ── Fallback: return all obligations for the scope ─────────────
        if multi or portfolio:
            grouped = retriever.get_obligations_grouped_by_contract(
                contract_ids=scope_ids,
            )
            return format_cross_contract_result(
                question, "all_obligations_fallback", grouped, retriever,
            )
        facts = retriever.get_all_obligations(
            contract_id=contract_id, contract_ids=scope_ids,
        )
        return format_graph_result(question, "all_obligations_fallback", facts, retriever)

    finally:
        retriever.close()
