"""
Graph-native retriever for Contract360.

Queries Cosmos Gremlin directly for structured semantic facts.
Supports:
  - Single-contract scoped queries  (contract_id set)
  - Multi-contract scoped queries   (contract_ids list)
  - Portfolio-wide queries          (no filter)
  - Cross-contract analysis         (shared parties, comparative obligations)

Route: "graph" — no Azure AI Search involved.

Vocabulary alignment: retriever queries cover the full canonical ontology
defined in app/kg/legal_extractor.py (LEGAL_NODE_TYPES /
LEGAL_RELATIONSHIP_TYPES).  Both the Rules-vocab subset
(Obligation/Right/Restriction + OWED_BY/OWED_TO/HAS_DEADLINE) AND the
richer Allowed-list vocab (Indemnitor/Indemnitee/TerminationEvent etc.) are
handled.
"""

import logging
from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.kg.gremlin_writer import GremlinWriter

logger = logging.getLogger(__name__)


# ── Canonical label sets ───────────────────────────────────────────────────────

# All vertex labels that represent a named party or party-role.
# Used by get_shared_parties and party-scoped queries.
PARTY_LABELS = [
    "Party", "Obligor", "Obligee", "Indemnitor", "Indemnitee",
    "BreachingParty", "NonBreachingParty", "NoticeRecipient",
    "Assignor", "Assignee", "ThirdParty",
]

# hasLabel() argument string for Gremlin (comma-separated quoted values)
_PARTY_LABEL_ARGS = ", ".join(f"'{l}'" for l in PARTY_LABELS)

# Edge types that link a party-role vertex to an Obligation
_OBLIGATION_EDGES = ["OWED_BY", "OBLIGATES", "IMPOSES_OBLIGATION_ON", "TRIGGERS_OBLIGATION_OF"]


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
    if contract_ids:
        clauses = ", ".join(f"has('contractId', '{cid}')" for cid in contract_ids)
        return f".or({clauses})"
    return ""


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
            "kgId":           first_value(item, "kgId"),
            "name":           first_value(item, "name"),
            "contractId":     first_value(item, "contractId"),
            "legalType":      first_value(item, "legalType"),
            "confidence":     first_value(item, "confidence"),
            "evidenceQuote":  first_value(item, "evidenceQuote"),
            "sourceClauseId": first_value(item, "sourceClauseId"),
        }
        for item in items
    ]


def _dedup(items: List[Dict], key: str = "kgId") -> List[Dict]:
    seen, out = set(), []
    for item in items:
        k = item.get(key)
        if k and k not in seen:
            seen.add(k)
            out.append(item)
        elif not k:
            out.append(item)
    return out


# ── GraphNativeRetriever ───────────────────────────────────────────────────────

class GraphNativeRetriever:
    def __init__(self):
        self.writer = GremlinWriter()

    def close(self):
        self.writer.close()

    # ------------------------------------------------------------------
    # Obligation queries
    # ------------------------------------------------------------------

    def get_obligations_by_party(
        self,
        party_name: str,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Obligations owed BY a named party (OWED_BY path + Obligor path)."""
        cf = _contract_filter_step(contract_id, contract_ids)

        # Rules vocab: Obligation -OWED_BY-> Party
        q1 = f"""
        g.V().hasLabel('Party').has('name', party_name){cf}
          .in('OWED_BY').hasLabel('Obligation').dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r1 = normalize_items(self.writer.submit(q1, {"party_name": party_name}))

        # Allowed-list vocab: Obligor -OBLIGATES-> Obligation
        q2 = f"""
        g.V().hasLabel('Obligor').has('name', party_name){cf}
          .out('OBLIGATES').dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r2 = normalize_items(self.writer.submit(q2, {"party_name": party_name}))

        return _dedup(r1 + r2)

    def get_obligations_owed_to_party(
        self,
        party_name: str,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Obligations owed TO a named party (OWED_TO path + Obligee path)."""
        cf = _contract_filter_step(contract_id, contract_ids)

        q1 = f"""
        g.V().hasLabel('Party').has('name', party_name){cf}
          .in('OWED_TO').hasLabel('Obligation').dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r1 = normalize_items(self.writer.submit(q1, {"party_name": party_name}))

        q2 = f"""
        g.V().hasLabel('Obligee').has('name', party_name){cf}
          .in('OBLIGATES').dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r2 = normalize_items(self.writer.submit(q2, {"party_name": party_name}))

        return _dedup(r1 + r2)

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
            .by(valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId'))
            .by(valueMap('kgId', 'name', 'evidenceQuote'))
        """
        result = self.writer.submit(query)
        items = []
        for row in result:
            o = row.get("obligation", {})
            d = row.get("deadline", {})
            items.append({
                "kgId":             first_value(o, "kgId"),
                "name":             first_value(o, "name"),
                "contractId":       first_value(o, "contractId"),
                "legalType":        first_value(o, "legalType"),
                "confidence":       first_value(o, "confidence"),
                "evidenceQuote":    first_value(o, "evidenceQuote"),
                "sourceClauseId":   first_value(o, "sourceClauseId"),
                "deadlineName":     first_value(d, "name"),
                "deadlineEvidence": first_value(d, "evidenceQuote"),
            })
        return _filter_by_contracts(items, contract_id, contract_ids)

    def get_all_obligations(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """All Obligation vertices — direct + reached via Obligor->OBLIGATES."""
        cf = _contract_filter_step(contract_id, contract_ids)

        q1 = f"""
        g.V().hasLabel('Obligation'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r1 = normalize_items(self.writer.submit(q1))

        # Also catch obligations reachable via Obligor
        q2 = f"""
        g.V().hasLabel('Obligor'){cf}
          .out('OBLIGATES').hasLabel('Obligation').dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        r2 = normalize_items(self.writer.submit(q2))

        return _dedup(r1 + r2)

    def get_rights(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Right'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
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
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    # ------------------------------------------------------------------
    # Indemnification
    # ------------------------------------------------------------------

    def get_indemnity_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Indemnitor -INDEMNIFIES-> Indemnitee pairs + standalone Indemnitor/Indemnitee vertices."""
        cf = _contract_filter_step(contract_id, contract_ids)

        # Relationship-based (richer)
        q1 = f"""
        g.V().hasLabel('Indemnitor'){cf}.as('ind')
          .out('INDEMNIFIES').hasLabel('Indemnitee').as('indt')
          .select('ind', 'indt')
          .by(valueMap('kgId', 'name', 'contractId', 'evidenceQuote', 'sourceClauseId'))
          .by(valueMap('kgId', 'name'))
        """
        items = []
        for row in self.writer.submit(q1):
            ind  = row.get("ind", {})
            indt = row.get("indt", {})
            items.append({
                "kgId":          first_value(ind, "kgId"),
                "name":          f"{first_value(ind, 'name')} indemnifies {first_value(indt, 'name')}",
                "indemnitor":    first_value(ind, "name"),
                "indemnitee":    first_value(indt, "name"),
                "contractId":    first_value(ind, "contractId"),
                "evidenceQuote": first_value(ind, "evidenceQuote"),
                "sourceClauseId": first_value(ind, "sourceClauseId"),
                "confidence":    None,
            })

        # Standalone Indemnitor vertices (no paired Indemnitee edge found)
        q2 = f"""
        g.V().hasLabel('Indemnitor', 'Indemnitee'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        standalone = normalize_items(self.writer.submit(q2))
        # Only include if not already covered by a paired result
        paired_ids = {i["kgId"] for i in items if i.get("kgId")}
        for s in standalone:
            if s.get("kgId") not in paired_ids:
                items.append(s)

        return items

    # ------------------------------------------------------------------
    # Termination / breach / cure
    # ------------------------------------------------------------------

    def get_termination_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('TerminationEvent', 'TerminationRight'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    def get_breach_cure_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        cf = _contract_filter_step(contract_id, contract_ids)
        query = f"""
        g.V().hasLabel('Breach', 'CurePeriod'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        return normalize_items(self.writer.submit(query))

    # ------------------------------------------------------------------
    # Notice
    # ------------------------------------------------------------------

    def get_notice_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Notice vertices + GIVES_NOTICE_TO / PROVIDES_NOTICE_TO edges + NoticeRecipient vertices."""
        cf = _contract_filter_step(contract_id, contract_ids)

        # Relationship-based
        q1 = f"""
        g.V().hasLabel('Notice'){cf}.as('notice')
          .out('GIVES_NOTICE_TO', 'PROVIDES_NOTICE_TO').as('recipient')
          .select('notice', 'recipient')
          .by(valueMap('kgId', 'name', 'contractId', 'evidenceQuote', 'sourceClauseId'))
          .by(valueMap('kgId', 'name'))
        """
        items = []
        for row in self.writer.submit(q1):
            n = row.get("notice", {})
            r = row.get("recipient", {})
            items.append({
                "kgId":           first_value(n, "kgId"),
                "name":           first_value(n, "name"),
                "recipient":      first_value(r, "name"),
                "contractId":     first_value(n, "contractId"),
                "evidenceQuote":  first_value(n, "evidenceQuote"),
                "sourceClauseId": first_value(n, "sourceClauseId"),
                "confidence":     None,
            })

        # Standalone Notice / NoticeRecipient vertices
        q2 = f"""
        g.V().hasLabel('Notice', 'NoticeRecipient', 'NoticePeriod'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        seen = {i["kgId"] for i in items if i.get("kgId")}
        for s in normalize_items(self.writer.submit(q2)):
            if s.get("kgId") not in seen:
                items.append(s)

        return items

    # ------------------------------------------------------------------
    # Payment / financial
    # ------------------------------------------------------------------

    def get_payment_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Invoice/ReimbursableCost vertices + PAYS/MAKES_PAYMENT_TO/REIMBURSES edges."""
        cf = _contract_filter_step(contract_id, contract_ids)

        # Structural payment vertices
        q1 = f"""
        g.V().hasLabel('Invoice', 'ReimbursableCost', 'InterestRate'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        items = list(normalize_items(self.writer.submit(q1)))

        # Payment relationship: payer -PAYS/MAKES_PAYMENT_TO/REIMBURSES-> payee
        q2 = f"""
        g.V().hasLabel({_PARTY_LABEL_ARGS}){cf}.as('payer')
          .out('PAYS', 'MAKES_PAYMENT_TO', 'REIMBURSES').as('payee')
          .select('payer', 'payee')
          .by(valueMap('kgId', 'name', 'contractId', 'evidenceQuote', 'sourceClauseId'))
          .by(valueMap('kgId', 'name'))
        """
        for row in self.writer.submit(q2):
            p  = row.get("payer", {})
            pe = row.get("payee", {})
            items.append({
                "kgId":           first_value(p, "kgId"),
                "name":           f"{first_value(p, 'name')} pays {first_value(pe, 'name')}",
                "contractId":     first_value(p, "contractId"),
                "evidenceQuote":  first_value(p, "evidenceQuote"),
                "sourceClauseId": first_value(p, "sourceClauseId"),
                "confidence":     None,
                "legalType":      None,
            })

        return _dedup(items)

    # ------------------------------------------------------------------
    # Liability
    # ------------------------------------------------------------------

    def get_liability_facts(
        self,
        contract_id: Optional[str] = None,
        contract_ids: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Liability vertices + CAPS_LIABILITY_OF relationships."""
        cf = _contract_filter_step(contract_id, contract_ids)

        q1 = f"""
        g.V().hasLabel('Liability'){cf}.dedup()
          .valueMap('kgId', 'name', 'contractId', 'legalType', 'confidence', 'evidenceQuote', 'sourceClauseId')
        """
        items = list(normalize_items(self.writer.submit(q1)))

        # Liability cap relationships: capper -CAPS_LIABILITY_OF-> capped_party
        q2 = f"""
        g.V(){cf}.as('capper')
          .outE('CAPS_LIABILITY_OF').as('e')
          .inV().as('capped')
          .select('capper', 'capped')
          .by(valueMap('kgId', 'name', 'contractId', 'evidenceQuote', 'sourceClauseId'))
          .by(valueMap('kgId', 'name'))
        """
        for row in self.writer.submit(q2):
            a = row.get("capper", {})
            b = row.get("capped", {})
            items.append({
                "kgId":           first_value(a, "kgId"),
                "name":           f"{first_value(a, 'name')} caps liability of {first_value(b, 'name')}",
                "contractId":     first_value(a, "contractId"),
                "evidenceQuote":  first_value(a, "evidenceQuote"),
                "sourceClauseId": first_value(a, "sourceClauseId"),
                "confidence":     None,
                "legalType":      "LiabilityCap",
            })

        return _dedup(items)

    # ------------------------------------------------------------------
    # Clause metadata
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Cross-contract queries
    # ------------------------------------------------------------------

    def get_shared_parties(self, contract_ids: Optional[List[str]] = None) -> Dict[str, List[str]]:
        """
        Return parties/party-roles that appear in more than one contract.
        Queries ALL party-role labels, not just 'Party'.
        { party_name: [contractId, ...] }
        """
        query = f"""
        g.V().hasLabel({_PARTY_LABEL_ARGS}).dedup()
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
        return {
            name: sorted(set(cids))
            for name, cids in party_contracts.items()
            if len(set(cids)) > 1
        }

    def get_obligations_grouped_by_contract(
        self,
        contract_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        items = self.get_all_obligations(contract_ids=contract_ids)
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            grouped[item.get("contractId") or "unknown"].append(item)
        return dict(grouped)

    def get_deadlines_grouped_by_contract(
        self,
        contract_ids: Optional[List[str]] = None,
    ) -> Dict[str, List[Dict]]:
        items = self.get_obligations_with_deadlines(contract_ids=contract_ids)
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            grouped[item.get("contractId") or "unknown"].append(item)
        return dict(grouped)

    def _group_by_contract(self, items: List[Dict]) -> Dict[str, List[Dict]]:
        grouped: Dict[str, List[Dict]] = defaultdict(list)
        for item in items:
            grouped[item.get("contractId") or "unknown"].append(item)
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

        label = fact.get("name") or "(unnamed)"
        if fact.get("legalType"):
            label = f"[{fact['legalType']}] {label}"
        lines.append(f"  {idx}. {label}")

        if show_contract and fact.get("contractId"):
            lines.append(f"     Contract: {fact.get('contractId')}")
        # Relationship-specific sub-fields
        if fact.get("indemnitor"):
            lines.append(f"     Indemnitor: {fact['indemnitor']}  →  Indemnitee: {fact.get('indemnitee', '?')}")
        if fact.get("recipient"):
            lines.append(f"     Notice recipient: {fact['recipient']}")
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
    header = [
        "=" * 80, "GRAPH RETRIEVAL", "=" * 80,
        f"Question: {question}", f"Intent: {intent}",
        f"Facts found: {len(facts)}", "",
    ]
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
        lines.append(
            f"── {contract_id} ({len(facts)} facts) " + "─" * max(0, 60 - len(contract_id))
        )
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
    Covers the full canonical ontology: obligations, rights, restrictions,
    indemnity, termination, breach/cure, notice, payment, liability.
    """
    q = question.lower()

    # Resolve effective scope
    scope_ids: Optional[List[str]] = None
    if contract_ids:
        scope_ids = contract_ids
    elif contract_id:
        scope_ids = [contract_id]
    multi     = scope_ids is not None and len(scope_ids) > 1
    portfolio = scope_ids is None

    retriever = GraphNativeRetriever()
    try:
        party = extract_party(question)

        # ── Deadline questions ─────────────────────────────────────────
        if "deadline" in q or "due date" in q or "by when" in q:
            if multi or portfolio:
                grouped = retriever.get_deadlines_grouped_by_contract(contract_ids=scope_ids)
                return format_cross_contract_result(question, "obligations_with_deadlines", grouped, retriever)
            facts = retriever.get_obligations_with_deadlines(contract_id=contract_id, contract_ids=scope_ids)
            return format_graph_result(question, "obligations_with_deadlines", facts, retriever)

        # ── Indemnification ────────────────────────────────────────────
        if "indemnif" in q or "indemnit" in q or "hold harmless" in q:
            facts = retriever.get_indemnity_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "indemnity", grouped, retriever)
            return format_graph_result(question, "indemnity", facts, retriever, multi_contract=portfolio)

        # ── Termination ────────────────────────────────────────────────
        if "terminat" in q or "termination" in q:
            facts = retriever.get_termination_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "termination", grouped, retriever)
            return format_graph_result(question, "termination", facts, retriever, multi_contract=portfolio)

        # ── Breach / cure / default ────────────────────────────────────
        if "breach" in q or "cure" in q or "default" in q:
            facts = retriever.get_breach_cure_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "breach_cure", grouped, retriever)
            return format_graph_result(question, "breach_cure", facts, retriever, multi_contract=portfolio)

        # ── Notice ─────────────────────────────────────────────────────
        if "notice" in q or "notif" in q or "notice period" in q:
            facts = retriever.get_notice_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "notice", grouped, retriever)
            return format_graph_result(question, "notice", facts, retriever, multi_contract=portfolio)

        # ── Payment / invoicing / reimbursement ───────────────────────
        if any(t in q for t in ["payment", "invoice", "reimburse", "pay ", "pays ", "billing"]):
            facts = retriever.get_payment_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "payment", grouped, retriever)
            return format_graph_result(question, "payment", facts, retriever, multi_contract=portfolio)

        # ── Liability / caps ───────────────────────────────────────────
        if "liabilit" in q or "liability cap" in q or "cap " in q:
            facts = retriever.get_liability_facts(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "liability", grouped, retriever)
            return format_graph_result(question, "liability", facts, retriever, multi_contract=portfolio)

        # ── Shared party / cross-contract analysis ─────────────────────
        cross_triggers = [
            "across contracts", "compare", "shared parties", "both contracts",
            "all contracts", "portfolio", "multiple contracts",
        ]
        if any(t in q for t in cross_triggers) or (portfolio and party is None):
            shared  = retriever.get_shared_parties(contract_ids=scope_ids)
            grouped = retriever.get_obligations_grouped_by_contract(contract_ids=scope_ids)
            extra = []
            if shared:
                extra.append("\n── Parties Appearing in Multiple Contracts ─────────────")
                for pname, cids in sorted(shared.items()):
                    extra.append(f"  {pname}: {', '.join(cids)}")
            return format_cross_contract_result(
                question, "cross_contract_analysis", grouped, retriever, extra_sections=extra,
            )

        # ── Party-owed-to ──────────────────────────────────────────────
        if "owed to" in q and party:
            if multi or portfolio:
                facts = retriever.get_obligations_owed_to_party(party, contract_ids=scope_ids)
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, f"obligations_owed_to:{party}", grouped, retriever)
            facts = retriever.get_obligations_owed_to_party(party, contract_id=contract_id, contract_ids=scope_ids)
            return format_graph_result(question, f"obligations_owed_to:{party}", facts, retriever)

        # ── Party obligation ───────────────────────────────────────────
        if ("obligation" in q or "responsible" in q or "owe" in q or "owed" in q) and party:
            if multi or portfolio:
                facts = retriever.get_obligations_by_party(party, contract_ids=scope_ids)
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, f"obligations_by_party:{party}", grouped, retriever)
            facts = retriever.get_obligations_by_party(party, contract_id=contract_id, contract_ids=scope_ids)
            return format_graph_result(question, f"obligations_by_party:{party}", facts, retriever)

        # ── All obligations (no specific party) ────────────────────────
        if "obligation" in q or "responsible" in q:
            if multi or portfolio:
                grouped = retriever.get_obligations_grouped_by_contract(contract_ids=scope_ids)
                return format_cross_contract_result(question, "all_obligations", grouped, retriever)
            facts = retriever.get_all_obligations(contract_id=contract_id, contract_ids=scope_ids)
            return format_graph_result(question, "all_obligations", facts, retriever)

        # ── Rights ─────────────────────────────────────────────────────
        if "right" in q or "entitl" in q or "permission" in q:
            facts = retriever.get_rights(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "rights", grouped, retriever)
            return format_graph_result(question, "rights", facts, retriever, multi_contract=multi or portfolio)

        # ── Restrictions ───────────────────────────────────────────────
        if "restriction" in q or "prohibit" in q or "shall not" in q or "may not" in q:
            facts = retriever.get_restrictions(contract_id=contract_id, contract_ids=scope_ids)
            if multi or portfolio:
                grouped = retriever._group_by_contract(facts)
                return format_cross_contract_result(question, "restrictions", grouped, retriever)
            return format_graph_result(question, "restrictions", facts, retriever, multi_contract=multi or portfolio)

        # ── Fallback: obligations ──────────────────────────────────────
        if multi or portfolio:
            grouped = retriever.get_obligations_grouped_by_contract(contract_ids=scope_ids)
            return format_cross_contract_result(question, "all_obligations_fallback", grouped, retriever)
        facts = retriever.get_all_obligations(contract_id=contract_id, contract_ids=scope_ids)
        return format_graph_result(question, "all_obligations_fallback", facts, retriever)

    finally:
        retriever.close()
