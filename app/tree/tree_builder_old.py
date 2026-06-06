import json
import re
import uuid
from pathlib import Path
from typing import List, Optional
from app.models import TreeNode

HEADING_RE = re.compile(r'^(?P<num>\d+(?:\.\d+)*\.?)\s+[A-Z][A-Za-z0-9 ,/&()\-]{2,160}$')
PAGE_RE = re.compile(r'^\[PAGE\s+(\d+)\]$', re.IGNORECASE)

def load_pageindex_tree(path: str, contract_id: str) -> TreeNode:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    if isinstance(raw, dict) and "tree" in raw:
        tree_raw = raw["tree"]
    elif isinstance(raw, dict) and "root" in raw:
        tree_raw = raw["root"]
    else:
        tree_raw = raw

    root = _tree_node_from_any(tree_raw, contract_id=contract_id)

    if not root.nodeId:
        root.nodeId = f"doc_{contract_id}"

    if not root.title or root.title == "Untitled":
        root.title = contract_id

    root.nodeType = root.nodeType or "document"

    normalize_tree(root, None, [])

    return root


def _tree_node_from_any(raw, contract_id: str) -> TreeNode:
    """
    Accepts unknown PageIndex tree shapes and maps them to our TreeNode schema.
    """

    if isinstance(raw, list):
        return TreeNode(
            nodeId=f"doc_{contract_id}",
            nodeType="document",
            title=contract_id,
            text="",
            children=[_tree_node_from_any(x, contract_id) for x in raw]
        )

    if not isinstance(raw, dict):
        return TreeNode(
            nodeId=f"node_{uuid.uuid4().hex[:8]}",
            nodeType="section",
            title="Untitled",
            text=str(raw or ""),
            children=[]
        )

    children_raw = (
        raw.get("children")
        or raw.get("sub_nodes")
        or raw.get("subNodes")
        or raw.get("nodes")
        or raw.get("sections")
        or []
    )

    title = (
        raw.get("title")
        or raw.get("heading")
        or raw.get("name")
        or raw.get("label")
        or raw.get("summary")
        or "Untitled"
    )

    text = (
        raw.get("text")
        or raw.get("content")
        or raw.get("page_content")
        or raw.get("pageContent")
        or raw.get("markdown")
        or raw.get("body")
        or ""
    )

    node_type = (
        raw.get("nodeType")
        or raw.get("node_type")
        or raw.get("type")
        or raw.get("kind")
        or "section"
    )

    node_id = (
        raw.get("nodeId")
        or raw.get("node_id")
        or raw.get("id")
        or f"{node_type}_{uuid.uuid4().hex[:8]}"
    )

    page_start = (
        raw.get("pageStart")
        or raw.get("page_start")
        or raw.get("start_page")
        or raw.get("startPage")
        or raw.get("page")
    )

    page_end = (
        raw.get("pageEnd")
        or raw.get("page_end")
        or raw.get("end_page")
        or raw.get("endPage")
        or page_start
    )

    return TreeNode(
        nodeId=str(node_id),
        nodeType=str(node_type),
        title=str(title),
        text=str(text or ""),
        pageStart=page_start,
        pageEnd=page_end,
        sourcePath=raw.get("sourcePath") or raw.get("path"),
        children=[_tree_node_from_any(c, contract_id) for c in children_raw]
    )


def normalize_tree(node: TreeNode, parent_id: Optional[str], path: List[str]) -> None:
    if not node.nodeId:
        node.nodeId = f"{node.nodeType}_{uuid.uuid4().hex[:8]}"

    if not node.nodeType:
        node.nodeType = "section"

    if not node.title:
        node.title = node.nodeId

    node.parentNodeId = parent_id
    node.sourcePath = " > ".join(path + [node.title])

    if node.pageEnd is None:
        node.pageEnd = node.pageStart

    for child in node.children:
        normalize_tree(child, node.nodeId, path + [node.title])

ARTICLE_RE = re.compile(
    r"^ARTICLE\s+(?P<num>[IVXLCDM]+|\d+)\s*[:.\-]?\s*(?P<title>[A-Z0-9 ,/&()'\-]*)$"
)

EXHIBIT_RE = re.compile(
    r"^EXHIBIT\s+(?P<num>[A-Z0-9]+)\s*[:.\-]?\s*(?P<title>[A-Z0-9 ,/&()'\-]*)$"
)

APPENDIX_RE = re.compile(
    r"^APPENDIX\s+(?P<num>[A-Z0-9]+)\s*[:.\-]?\s*(?P<title>[A-Z0-9 ,/&()'\-]*)$"
)

SECTION_RE = re.compile(
    r"^SECTION\s+(?P<num>\d+(?:\.\d+)*)\s*[:.\-]?\s*(?P<title>.+)$",
    re.IGNORECASE
)

NUMERIC_RE = re.compile(
    r"^(?P<num>\d+(?:\.\d+)+|\d+\.)\s+(?P<title>.{3,220})$"
)

PAGE_RE = re.compile(r"^\[PAGE\s+(\d+)\]$", re.IGNORECASE)

def _is_toc_line(line: str) -> bool:
    upper = line.upper()
    return (
        "TABLE OF CONTENTS" in upper
        or re.match(r"^ARTICLE\s+[IVXLCDM\d]+.*\s+\d+$", upper) is not None
        or re.match(r"^EXHIBIT\s+[A-Z0-9]+.*", upper) is not None
        or re.match(r"^APPENDIX\s+[A-Z0-9]+.*", upper) is not None
    )


def _is_bad_heading_candidate(line: str) -> bool:
    clean = line.strip()
    upper = clean.upper()

    # Reject likely addresses/contact lines
    if re.search(r"\b(STREET|ST\.|ROAD|RD\.|AVENUE|AVE\.|PLACE|NY|NEW YORK|PHONE|TELEPHONE|E-MAIL|EMAIL)\b", upper):
        return True

    # Reject email/contact lines
    if "@" in clean:
        return True

    # Reject very long sentence-like lines
    if len(clean) > 240:
        return True

    # Reject lines ending with comma, usually continuation lines
    if clean.endswith(","):
        return True

    return False


def _detect_heading(line: str):
    clean = line.strip()

    if not clean:
        return None

    if _is_bad_heading_candidate(clean):
        return None

    # ARTICLE headings must be uppercase ARTICLE, not inline "Article XXI"
    m = ARTICLE_RE.match(clean)
    if m:
        return {
            "level": 1,
            "nodeType": "section",
            "title": clean,
            "headingType": "article"
        }

    m = EXHIBIT_RE.match(clean)
    if m:
        return {
            "level": 1,
            "nodeType": "section",
            "title": clean,
            "headingType": "exhibit"
        }

    m = APPENDIX_RE.match(clean)
    if m:
        return {
            "level": 1,
            "nodeType": "section",
            "title": clean,
            "headingType": "appendix"
        }

    m = SECTION_RE.match(clean)
    if m:
        num = m.group("num")
        return {
            "level": num.count(".") + 1,
            "nodeType": "clause" if "." in num else "section",
            "title": clean,
            "headingType": "section"
        }

    m = NUMERIC_RE.match(clean)
    if m:
        num = m.group("num").rstrip(".")
        title = m.group("title").strip()

        # Reject if title looks like address/contact
        if _is_bad_heading_candidate(title):
            return None

        # Reject if numeric part is plain number without dot hierarchy and title looks address-like
        if "." not in num and not m.group("num").endswith("."):
            return None

        level = num.count(".") + 1

        return {
            "level": level,
            "nodeType": "section" if level == 1 else "clause",
            "title": clean,
            "headingType": "numeric"
        }

    return None


def build_fallback_tree(text: str, contract_id: str) -> TreeNode:
    root = TreeNode(
        nodeId=f"doc_{contract_id}",
        nodeType="document",
        title=contract_id,
        pageStart=1,
        pageEnd=1,
        sourcePath=contract_id
    )

    seen_first_article = False
    current_page = 1
    current = root
    buffer = []

    # Important: level map avoids 3.1.2 becoming child of 3.1.1
    level_nodes = {0: root}

    in_toc = False
    toc_line_count = 0

    def flush():
        nonlocal buffer, current
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                current.text = (current.text + "\n" + content).strip()
                current.pageEnd = current_page
            buffer = []

    for raw in text.splitlines():
        line = raw.strip()

        page_match = PAGE_RE.match(line)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        if not line:
            continue

        # TOC detection
        if "TABLE OF CONTENTS" in line.upper():
            in_toc = True
            toc_line_count = 0
            continue

        if in_toc:
            toc_line_count += 1

            # Leave TOC when actual body begins
            heading = _detect_heading(line)

            if heading and toc_line_count > 5 and not _is_toc_line(line):
                in_toc = False
            else:
                continue

        heading = _detect_heading(line)

        if heading and heading["headingType"] == "article":
            seen_first_article = True

        # Before the first ARTICLE, don't create random sections.
        # Keep cover/preamble text at document root.
        if heading and not seen_first_article and heading["headingType"] not in {"article", "exhibit", "appendix"}:
            buffer.append(raw)
            continue

        if heading:
            flush()

            level = heading["level"]
            node_type = heading["nodeType"]
            title = heading["title"]

            # Find nearest available parent level below current level
            parent_level_candidates = [lvl for lvl in level_nodes.keys() if lvl < level]

            if parent_level_candidates:
                parent_level = max(parent_level_candidates)
            else:
                parent_level = 0

            parent = level_nodes[parent_level]

            node = TreeNode(
                nodeId=f"{node_type}_{contract_id}_{uuid.uuid4().hex[:8]}",
                nodeType=node_type,
                title=title,
                text="",
                parentNodeId=parent.nodeId,
                pageStart=current_page,
                pageEnd=current_page,
                sourcePath=f"{parent.sourcePath} > {title}",
                children=[]
            )

            parent.children.append(node)

            # Replace this level and clear deeper levels
            level_nodes[level] = node
            for deeper in [lvl for lvl in list(level_nodes.keys()) if lvl > level]:
                del level_nodes[deeper]

            current = node

        else:
            buffer.append(raw)

    flush()

    root.pageEnd = current_page

    # Full-document fallback if parser found no usable text nodes
    has_text_nodes = any(
        n.text.strip()
        for n in flatten_tree(root)
        if n.nodeType != "document"
    )

    if not root.children or not has_text_nodes:
        root.children = [
            TreeNode(
                nodeId=f"section_{contract_id}_full_document",
                nodeType="section",
                title="Full Document",
                text=text.strip(),
                parentNodeId=root.nodeId,
                pageStart=1,
                pageEnd=current_page,
                sourcePath=f"{contract_id} > Full Document",
                children=[]
            )
        ]

    return root


def flatten_tree(root: TreeNode) -> List[TreeNode]:
    out = []
    def walk(n: TreeNode):
        out.append(n)
        for c in n.children:
            walk(c)
    walk(root)
    return out
