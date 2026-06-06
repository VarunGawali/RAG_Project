import json
import re
import hashlib
from pathlib import Path
from typing import Dict, Any, List, Optional

from app import config
from app.kg.models import KGNode, KGEdge, NormalizedContract


# ---------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------

def slugify(value: str, max_len: int = 120) -> str:
    """
    Convert text into a safe ID component.
    """
    value = value or "unknown"
    value = value.strip()
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value[:max_len] or "unknown"


def short_hash(value: str, length: int = 8) -> str:
    """
    Stable short hash for fallback IDs.
    """
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def safe_json_preview(obj: Any, limit: int = 1000) -> str:
    """
    Safely stringify JSON-like object for hashing/debugging.
    """
    try:
        return json.dumps(obj, ensure_ascii=False)[:limit]
    except Exception:
        return str(obj)[:limit]


def clean_section_for_id(section_number: Optional[str]) -> Optional[str]:
    """
    Convert section/article number to clean ID component.
    Example:
      ARTICLE XXXIV -> ARTICLE_XXXIV
      10.2 -> 10_2
    """
    if not section_number:
        return None
    return slugify(section_number)


# ---------------------------------------------------------------------
# Contract/tree inference helpers
# ---------------------------------------------------------------------

def infer_contract_id(tree: Dict[str, Any]) -> str:
    """
    Infer contract ID from existing tree structure.

    Supports:
    - contractId
    - documentId
    - root nodeId starting with doc_
    - title fallback
    """
    if tree.get("contractId"):
        return str(tree["contractId"])

    if tree.get("documentId"):
        return str(tree["documentId"]).replace("_doc", "")

    node_id = tree.get("nodeId")
    if node_id and str(node_id).startswith("doc_"):
        return str(node_id).replace("doc_", "")

    if tree.get("title"):
        return slugify(str(tree["title"]))

    return "contract_" + short_hash(safe_json_preview(tree))


def extract_section_number(title: Optional[str]) -> Optional[str]:
    """
    Extract section/article/exhibit/appendix number from node title.

    Examples:
    - ARTICLE XXXIV -> ARTICLE XXXIV
    - EXHIBIT E: -> EXHIBIT E
    - APPENDIX F -> APPENDIX F
    - 10.2 Limitation of Liability -> 10.2
    - 4. Con Edison shall... -> 4
    """
    if not title:
        return None

    title = title.strip()

    # ARTICLE XXXIV / ARTICLE 1
    m = re.match(r"^(ARTICLE\s+[A-ZIVXLCDM0-9]+)", title, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # EXHIBIT E:
    m = re.match(r"^(EXHIBIT\s+[A-Z0-9]+)", title, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # APPENDIX F
    m = re.match(r"^(APPENDIX\s+[A-Z0-9]+)", title, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # Section number: 10, 10.2, 10.2(a), 4.
    m = re.match(r"^([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z]\))?)\.?", title)
    if m:
        return m.group(1)

    return None


def infer_node_type(raw_node: Dict[str, Any]) -> str:
    """
    Normalize existing node types into KG node types.
    """
    raw_type = str(raw_node.get("nodeType") or "").lower().strip()
    title = str(raw_node.get("title") or "").strip()

    if raw_type in {"doc", "document", "contract"}:
        return "contract"

    if re.match(r"^EXHIBIT\s+", title, re.IGNORECASE):
        return "exhibit"

    if re.match(r"^APPENDIX\s+", title, re.IGNORECASE):
        return "appendix"

    if raw_type in {"section", "clause", "definition", "table", "chunk"}:
        return raw_type

    if raw_type:
        return raw_type

    return "section"


def label_for_node_type(node_type: str) -> str:
    """
    Gremlin vertex label for a normalized node type.
    """
    mapping = {
        "contract": "Contract",
        "document": "Contract",
        "section": "Section",
        "clause": "Clause",
        "definition": "Definition",
        "exhibit": "Exhibit",
        "appendix": "Appendix",
        "table": "Table",
        "chunk": "Chunk",
    }
    return mapping.get(node_type, node_type.title())


def clause_title_suffix(title: str, section_number: Optional[str]) -> str:
    """
    Create readable suffix for duplicate clause numbers.

    Example:
      2.2.1 Written Notice -> written_notice
      2.2.1 End of Term Transition -> end_of_term_transition
    """
    if not title:
        return "clause"

    cleaned = title.strip()

    if section_number:
        cleaned = re.sub(
            r"^" + re.escape(section_number) + r"\.?\s*",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(r"^[\.\-\:\s]+", "", cleaned)
    suffix = slugify(cleaned, max_len=50)

    return suffix or "clause"


def make_kg_id(
    contract_id: str,
    node_type: str,
    raw_node: Dict[str, Any],
    parent_path: str = "",
    parent_kg_id: Optional[str] = None,
) -> str:
    """
    Create stable KG ID.

    For clauses, include:
    - parent article/section
    - section number
    - readable title suffix
    - short hash

    This avoids collisions when two clauses have same numbering.
    """
    title = raw_node.get("title") or ""
    raw_id = raw_node.get("nodeId") or ""
    section_number = extract_section_number(title)

    if node_type == "contract":
        return f"contract:{contract_id}"

    section_component = clean_section_for_id(section_number)

    if node_type == "clause":
        parent_component = (
            parent_kg_id.split(":")[-1]
            if parent_kg_id
            else slugify(parent_path, max_len=60)
        )

        suffix = clause_title_suffix(title, section_number)

        unique_source = raw_id or f"{parent_path}|{title}|{raw_node.get('text', '')}"
        unique_hash = short_hash(unique_source, length=6)

        return (
            f"clause:{contract_id}:"
            f"{parent_component}:"
            f"{section_component}:"
            f"{suffix}:"
            f"{unique_hash}"
        )

    if section_component:
        return f"{node_type}:{contract_id}:{section_component}"

    base = f"{parent_path}|{title}|{raw_id}"
    return f"{node_type}:{contract_id}:{short_hash(base)}"


def infer_clause_type_hint(
    title: Optional[str],
    text: Optional[str],
    node_type: str
) -> Optional[str]:
    """
    Lightweight rule-based clause/section type hint.
    This is only a hint. Legal extraction later creates actual semantic facts.
    """
    if node_type not in {"clause", "section", "definition"}:
        return None

    combined = f"{title or ''} {text or ''}".lower()

    rules = [
        ("definitions", ["definitions", "shall mean", "means:", "means "]),
        ("termination", ["termination", "terminate", "expiration", "expiry"]),
        ("payment", ["payment", "invoice", "fee", "fees", "compensation", "charges"]),
        ("liability", ["liability", "damages", "limitation of liability", "consequential damages"]),
        ("indemnity", ["indemnify", "indemnification", "hold harmless"]),
        ("confidentiality", ["confidential", "non-disclosure", "nondisclosure"]),
        ("governing_law", ["governing law", "laws of", "jurisdiction"]),
        ("notice", ["notice", "notify", "notification"]),
        ("reporting_obligation", ["submit", "report", "provide", "deliver", "furnish"]),
        ("maintenance", ["maintenance", "inspect", "inspection", "repair", "calibrate", "testing"]),
        ("environmental", ["environmental", "sf6", "hazardous", "release", "emissions", "leak"]),
        ("data_protection", ["personal data", "data protection", "privacy", "processor"]),
        ("assignment", ["assign", "assignment"]),
        ("force_majeure", ["force majeure"]),
        ("audit", ["audit", "inspect records", "inspection rights"]),
        ("insurance", ["insurance", "insured", "policy"]),
        ("warranty", ["warranty", "representations", "warranties"]),
        ("intellectual_property", ["intellectual property", "ip rights", "license"]),
        ("renewal", ["renewal", "auto-renew", "automatically renew"]),
    ]

    for label, keywords in rules:
        if any(keyword in combined for keyword in keywords):
            return label

    return None


def structural_edge_label(parent_label: str, child_label: str) -> str:
    """
    Pick structural edge label from parent to child.
    """
    if child_label == "Section":
        return "CONTAINS_SECTION"

    if child_label == "Clause":
        return "CONTAINS_CLAUSE"

    if child_label == "Exhibit":
        return "HAS_EXHIBIT"

    if child_label == "Appendix":
        return "HAS_APPENDIX"

    if child_label == "Definition":
        return "HAS_DEFINITION"

    if child_label == "Table":
        return "HAS_TABLE"

    if child_label == "Chunk":
        return "HAS_CHUNK"

    return "HAS_CHILD"


# ---------------------------------------------------------------------
# Main tree flattening
# ---------------------------------------------------------------------

def flatten_tree(
    raw_node: Dict[str, Any],
    contract_id: str,
    tenant_id: str,
    parent_kg_id: Optional[str],
    nodes: List[KGNode],
    edges: List[KGEdge],
    raw_to_kg: Dict[str, str],
    parent_path: str = "",
):
    """
    Recursive tree traversal.

    Converts each raw tree node into:
    - KGNode
    - structural KGEdge(s)
    """
    raw_node_id = raw_node.get("nodeId") or f"raw_{short_hash(safe_json_preview(raw_node, 500))}"
    node_type = infer_node_type(raw_node)
    label = label_for_node_type(node_type)

    kg_id = make_kg_id(
        contract_id=contract_id,
        node_type=node_type,
        raw_node=raw_node,
        parent_path=parent_path,
        parent_kg_id=parent_kg_id,
    )

    title = raw_node.get("title")
    text = raw_node.get("text")
    section_number = extract_section_number(title)
    source_path = raw_node.get("sourcePath") or parent_path or title or contract_id

    children = raw_node.get("children") or []

    node = KGNode(
        kgId=kg_id,
        rawNodeId=raw_node_id,
        contractId=contract_id,
        tenantId=tenant_id,
        nodeType=node_type,
        label=label,
        title=title,
        text=text,
        sectionNumber=section_number,
        pageStart=raw_node.get("pageStart"),
        pageEnd=raw_node.get("pageEnd"),
        sourcePath=source_path,
        parentKgId=parent_kg_id,
        childrenKgIds=[],
        siblingKgIds=[],
        clauseTypeHint=infer_clause_type_hint(title, text, node_type),
        extractionReady=node_type in {"clause", "definition", "section"},
        properties={
            "rawNodeId": raw_node_id,
            "itemType": raw_node.get("itemType"),
            "documentId": raw_node.get("documentId"),
            "parentNodeId": raw_node.get("parentNodeId"),
        },
    )

    nodes.append(node)
    raw_to_kg[raw_node_id] = kg_id

    # Parent -> child edge and child -> parent edge
    if parent_kg_id:
        parent_label = "Unknown"
        for existing_node in nodes:
            if existing_node.kgId == parent_kg_id:
                parent_label = existing_node.label
                break

        edge_label = structural_edge_label(parent_label, label)

        edges.append(
            KGEdge(
                edgeId=f"edge:{short_hash(parent_kg_id + edge_label + kg_id)}",
                sourceKgId=parent_kg_id,
                targetKgId=kg_id,
                label=edge_label,
                tenantId=tenant_id,
                properties={"edgeType": "structural"}
            )
        )

        edges.append(
            KGEdge(
                edgeId=f"edge:{short_hash(kg_id + 'HAS_PARENT' + parent_kg_id)}",
                sourceKgId=kg_id,
                targetKgId=parent_kg_id,
                label="HAS_PARENT",
                tenantId=tenant_id,
                properties={"edgeType": "structural"}
            )
        )

    # Precompute child KG IDs for current node
    child_kg_ids = []

    for child in children:
        child_type = infer_node_type(child)
        child_kg_id = make_kg_id(
            contract_id=contract_id,
            node_type=child_type,
            raw_node=child,
            parent_path=source_path,
            parent_kg_id=kg_id,
        )
        child_kg_ids.append(child_kg_id)

    node.childrenKgIds = child_kg_ids

    # Add NEXT_SIBLING / PREVIOUS_SIBLING edges among direct children
    for idx in range(len(child_kg_ids) - 1):
        current_id = child_kg_ids[idx]
        next_id = child_kg_ids[idx + 1]

        edges.append(
            KGEdge(
                edgeId=f"edge:{short_hash(current_id + 'NEXT_SIBLING' + next_id)}",
                sourceKgId=current_id,
                targetKgId=next_id,
                label="NEXT_SIBLING",
                tenantId=tenant_id,
                properties={"edgeType": "structural"}
            )
        )

        edges.append(
            KGEdge(
                edgeId=f"edge:{short_hash(next_id + 'PREVIOUS_SIBLING' + current_id)}",
                sourceKgId=next_id,
                targetKgId=current_id,
                label="PREVIOUS_SIBLING",
                tenantId=tenant_id,
                properties={"edgeType": "structural"}
            )
        )

    # Recurse
    for child in children:
        flatten_tree(
            raw_node=child,
            contract_id=contract_id,
            tenant_id=tenant_id,
            parent_kg_id=kg_id,
            nodes=nodes,
            edges=edges,
            raw_to_kg=raw_to_kg,
            parent_path=source_path,
        )


# ---------------------------------------------------------------------
# Public APIs
# ---------------------------------------------------------------------

def normalize_contract_tree(tree_path: str) -> NormalizedContract:
    """
    Load parsed tree JSON and return NormalizedContract.
    """
    path = Path(tree_path)

    if not path.exists():
        raise FileNotFoundError(f"Tree file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        tree = json.load(f)

    contract_id = infer_contract_id(tree)
    tenant_id = config.TENANT_ID

    nodes: List[KGNode] = []
    edges: List[KGEdge] = []
    raw_to_kg: Dict[str, str] = {}

    # Tree might already have a document root.
    # If not, wrap it as a contract/document node.
    root_type = str(tree.get("nodeType") or "").lower()

    if root_type not in {"doc", "document", "contract"}:
        root = {
            "nodeId": f"doc_{contract_id}",
            "nodeType": "document",
            "title": contract_id,
            "text": tree.get("text"),
            "pageStart": tree.get("pageStart"),
            "pageEnd": tree.get("pageEnd"),
            "sourcePath": contract_id,
            "children": tree.get("children", []),
            "contractId": contract_id,
            "documentId": tree.get("documentId"),
        }
    else:
        root = tree

    flatten_tree(
        raw_node=root,
        contract_id=contract_id,
        tenant_id=tenant_id,
        parent_kg_id=None,
        nodes=nodes,
        edges=edges,
        raw_to_kg=raw_to_kg,
        parent_path=contract_id,
    )

    # Fill sibling IDs on nodes
    parent_to_children: Dict[str, List[str]] = {}

    for node in nodes:
        if node.parentKgId:
            parent_to_children.setdefault(node.parentKgId, []).append(node.kgId)

    for node in nodes:
        if node.parentKgId and node.parentKgId in parent_to_children:
            node.siblingKgIds = [
                child_id
                for child_id in parent_to_children[node.parentKgId]
                if child_id != node.kgId
            ]

    return NormalizedContract(
        contractId=contract_id,
        tenantId=tenant_id,
        nodes=nodes,
        edges=edges,
    )


def save_normalized_contract(normalized: NormalizedContract, output_path: str):
    """
    Save normalized contract JSON.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(
            normalized.model_dump(),
            f,
            indent=2,
            ensure_ascii=False
        )


def default_normalized_output_path(contract_id: str) -> Path:
    """
    Default output path under data/kg/normalized.
    """
    return config.KG_NORMALIZED_DIR / f"{contract_id}_kg_ready.json"


# ---------------------------------------------------------------------
# Standalone local test
# ---------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser("normalize-tree")
    parser.add_argument("--tree", required=True, help="Path to parsed tree JSON")
    parser.add_argument("--output", default=None, help="Path to output normalized JSON")

    args = parser.parse_args()

    normalized_contract = normalize_contract_tree(args.tree)

    output = (
        Path(args.output)
        if args.output
        else default_normalized_output_path(normalized_contract.contractId)
    )

    save_normalized_contract(normalized_contract, str(output))

    print(json.dumps({
        "contractId": normalized_contract.contractId,
        "tenantId": normalized_contract.tenantId,
        "nodes": len(normalized_contract.nodes),
        "edges": len(normalized_contract.edges),
        "output": str(output),
    }, indent=2))