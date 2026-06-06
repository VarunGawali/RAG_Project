import json
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models import TreeNode


PAGE_RE = re.compile(r"^\[PAGE\s+(\d+)\]$", re.IGNORECASE)

ARTICLE_RE = re.compile(
    r"^ARTICLE\s+(?P<num>[IVXLCDM]+|\d+)(?:(?P<sep>[:.\-])\s*(?P<title>.{0,220})|\s+(?P<title2>[A-Z][A-Z0-9 ,;/&()'\-]{2,220}))?$",
    re.IGNORECASE,
)

EXHIBIT_RE = re.compile(
    r"^EXHIBIT\s+(?P<num>[A-Z]|\d+(?:-\d+)?|[A-Z]\.\d+|[A-Z]\d*)\s*[:.\-]?\s*(?P<title>[A-Z][A-Z0-9 ,;/&()'\-]{0,140})?$"
)

APPENDIX_RE = re.compile(
    r"^APPENDIX\s+(?P<num>[A-Z]|\d+(?:-\d+)?)\s*[:.\-]?\s*(?P<title>[A-Z][A-Z0-9 ,;/&()'\-]{0,140})?$"
)

SCHEDULE_RE = re.compile(
    r"^SCHEDULE\s+(?P<num>[A-Z]|\d+(?:-\d+)?)\s*[:.\-]?\s*(?P<title>[A-Z][A-Z0-9 ,;/&()'\-]{0,140})?$"
)

SECTION_RE = re.compile(
    r"^SECTION\s+(?P<num>\d+(?:\.\d+)*)\s+(?P<title>[A-Z][A-Za-z0-9 ,;/&()'\-]{2,180})$",
    re.IGNORECASE,
)

NUMERIC_CLAUSE_RE = re.compile(
    r"^(?P<num>\d+\.\d+(?:\.\d+)*\.?)\s+(?P<title>.{2,240})$"
)

NUMERIC_TOP_RE = re.compile(
    r"^(?P<num>\d+)\.\s+(?P<title>.{2,240})$"
)

ALL_CAPS_RE = re.compile(
    r"^[A-Z0-9][A-Z0-9 ,;/&()'\-]{4,140}$"
)


def _tree_node_from_any(raw: Any, contract_id: str) -> TreeNode:
    if isinstance(raw, list):
        return TreeNode(
            nodeId=f"doc_{contract_id}",
            nodeType="document",
            title=contract_id,
            text="",
            children=[_tree_node_from_any(x, contract_id) for x in raw],
        )

    if not isinstance(raw, dict):
        return TreeNode(
            nodeId=f"node_{uuid.uuid4().hex[:8]}",
            nodeType="section",
            title="Untitled",
            text=str(raw or ""),
            children=[],
        )

    children_raw = (
        raw.get("children")
        or raw.get("sub_nodes")
        or raw.get("subNodes")
        or raw.get("nodes")
        or raw.get("sections")
        or raw.get("structure")
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
        or raw.get("start_index")
        or raw.get("startIndex")
        or raw.get("page")
    )

    page_end = (
        raw.get("pageEnd")
        or raw.get("page_end")
        or raw.get("end_page")
        or raw.get("endPage")
        or raw.get("end_index")
        or raw.get("endIndex")
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
        children=[_tree_node_from_any(c, contract_id) for c in children_raw],
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


def _is_noise_line(line: str) -> bool:
    clean = line.strip()
    upper = clean.upper()

    if not clean:
        return True

    if PAGE_RE.match(clean):
        return False

    if "EXECUTION COPY" == upper:
        return True

    if "ALL TERMS, CONDITIONS, AND RATES" in upper:
        return True

    if re.match(r"^\d+\s*\|\s*PAGE$", upper):
        return True

    if re.match(r"^PAGE\s+\d+\s+OF\s+\d+$", upper):
        return True

    return False


def _is_bad_heading_candidate(line: str) -> bool:
    clean = line.strip()
    upper = clean.upper()

    if not clean:
        return True

    # Repeated headers / footers
    if _is_noise_line(clean):
        return True

    # Email / contact lines
    if "@" in clean:
        return True

    # Address-like headings
    if re.search(
        r"\b(STREET|ST\.|ROAD|RD\.|AVENUE|AVE\.|PLACE|DRIVE|LANE|BLVD|BOULEVARD|SUITE|NY|NEW YORK|CA|BRANCH ROAD)\b",
        upper,
    ):
        return True

    # Inline references, not headings
    if re.search(r"^\d+(?:\.\d+)+\s+of the .*Agreement", clean, re.IGNORECASE):
        return True

    if re.match(r"^(Exhibit|Appendix)\s+[A-Z0-9]+.*\bof this Agreement\b", clean, re.IGNORECASE):
        return True
    
        # Reject exhibit reference / placeholder text, not actual exhibit headings
    if re.match(r"^EXHIBIT\s+(IS|ARE|WAS|WERE|ATTACHED|ATTACHMENT)\b", clean, re.IGNORECASE):
        return True

    # Reject Bankruptcy Code section references like "366. Each Party..."
    if re.match(r"^366\.\s+", clean):
        return True
    
    # Reject inline exhibit/appendix/schedule references, not headings
    if re.match(
        r"^(Exhibit|Appendix|Schedule)\s+[A-Z0-9.\-]+\s+(attached|from|of|to|as|and|or|is|are|has|will|shall|means|sets?)\b",
        clean,
        re.IGNORECASE,
    ):
        return True

    # Reject short inline references like "Exhibit 3."
    if re.match(r"^(Exhibit|Appendix|Schedule)\s+\d+\.?$", clean, re.IGNORECASE):
        return True

    # Reject "Section 24;" / "Section 3.5," style references
    if re.match(r"^Section\s+\d+(?:\.\d+)*\s*[;,]?$", clean, re.IGNORECASE):
        return True
    
    # Reject TOC dot-leader lines even if they look like headings
    if re.search(r"\.{2,}\s*\d+\s*$", clean):
        return True

    # Too long to be a reliable heading
    if len(clean) > 260:
        return True
    
    # Reject inline exhibit references like "EXHIBIT C."
    # Real exhibit headings are usually "EXHIBIT C" without trailing period.
    if re.match(r"^EXHIBIT\s+[A-Z]\.$", clean, re.IGNORECASE):
        return True

    # Reject inline exhibit references like "EXHIBIT A. The District shall pay..."
    # Do not reject real exhibit identifiers like "EXHIBIT B.1".
    if re.match(r"^EXHIBIT\s+[A-Z]\.\s+.+", clean, re.IGNORECASE):
        return True

    # Reject inline appendix/schedule references with trailing period.
    if re.match(r"^(APPENDIX|SCHEDULE)\s+[A-Z]\.$", clean, re.IGNORECASE):
        return True

    # Continuation lines
    if clean.endswith(","):
        return True

    return False


def _looks_like_toc_line(line: str) -> bool:
    clean = line.strip()
    upper = clean.upper()

    if "TABLE OF CONTENTS" in upper:
        return True

    # Dot leader TOC lines:
    # ARTICLE III. TITLE ..17
    # ARTICLE III. TITLE ................................ 17
    # 2.1 Title .... 15
    if re.search(r"\.{2,}\s*\d+\s*$", clean):
        return True

    # ARTICLE I TITLE 10
    if re.match(r"^ARTICLE\s+[IVXLCDM\d]+.*\s+\d+$", upper):
        return True

    # 2.1 Title 15
    if re.match(r"^\d+(?:\.\d+)+\.?\s+.+\s+\d+$", clean):
        return True

    return False

def _preprocess_text(text: str) -> str:
    """
    Handles long-line PDFs like SoCal where ARTICLE/section headings are embedded
    inside one huge extracted line.
    """

    # Normalize spaces but preserve page markers.
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Insert line breaks before ARTICLE headings embedded in long lines.
    text = re.sub(
        r"\s+(ARTICLE\s+(?:[IVXLCDM]+|\d+)\.?\s+[A-Z][A-Z0-9 ,;/&()'\-]{3,})",
        r"\n\1",
        text,
    )

    # Insert line breaks before numeric clauses embedded in long lines.
    text = re.sub(
        r"\s+(\d+\.\d+(?:\.\d+)*\.?\s+[A-Z][A-Za-z0-9 ,;/&()'\-]{2,220})",
        r"\n\1",
        text,
    )

    # Insert line breaks before numeric top headings embedded in long lines.
    text = re.sub(
        r"\s+(\d+\.\s+[A-Z][A-Za-z0-9 ,;/&()'\-]{2,180})",
        r"\n\1",
        text,
    )

    # Insert line breaks before EXHIBIT / APPENDIX headings.
    text = re.sub(
        r"\s+((?:EXHIBIT|APPENDIX|SCHEDULE)\s+[A-Z0-9]+(?:\.\d+)?(?:\s*[:.\-]?\s*[A-Z][A-Z0-9 ,;/&()'\-]{0,140})?)",
        r"\n\1",
        text,
        flags=re.IGNORECASE,
    )

    return text


def _detect_heading(line: str) -> Optional[Dict[str, Any]]:
    clean = line.strip()

    if not clean:
        return None

    if _is_bad_heading_candidate(clean):
        return None

    m = ARTICLE_RE.match(clean)
    if m:
        sep = m.groupdict().get("sep")
        title = (
            m.groupdict().get("title")
            or m.groupdict().get("title2")
            or ""
        ).strip()
        num = m.group("num")

        # Reject inline references like:
        # Article 7.2.
        # Article 12.1.3, to assume...
        if re.match(r"^Article\s+\d+(?:\.\d+)+", clean, re.IGNORECASE):
            return None

        # Reject mixed-case inline references like "Article 16."
        # But allow real uppercase headings like "ARTICLE XVI"
        if clean.startswith("Article ") and not clean.startswith("ARTICLE "):
            return None

        # Reject "Article XII or require...", "Article XII do...", etc.
        if title.lower().startswith(("or ", "and ", "do ", "require ", "requires ", "shall ", "will ")):
            return None

        # If title exists, it should contain meaningful alphabetic heading text.
        if title:
            if not re.search(r"[A-Za-z]{3,}", title):
                return None

        return {
            "kind": "article",
            "level": 1,
            "number": num,
            "nodeType": "section",
            "title": clean,
        }

    m = EXHIBIT_RE.match(clean)
    if m:
        return {
            "kind": "exhibit",
            "level": 1,
            "number": m.group("num"),
            "nodeType": "section",
            "title": clean,
        }

    m = APPENDIX_RE.match(clean)
    if m:
        return {
            "kind": "appendix",
            "level": 1,
            "number": m.group("num"),
            "nodeType": "section",
            "title": clean,
        }

    m = SCHEDULE_RE.match(clean)
    if m:
        return {
            "kind": "schedule",
            "level": 1,
            "number": m.group("num"),
            "nodeType": "section",
            "title": clean,
        }

    m = SECTION_RE.match(clean)
    if m:
        num = m.group("num")
        return {
            "kind": "section_word",
            "level": num.count(".") + 1,
            "number": num,
            "nodeType": "clause" if "." in num else "section",
            "title": clean,
        }

    m = NUMERIC_CLAUSE_RE.match(clean)
    if m:
        raw_num = m.group("num")
        num = raw_num.rstrip(".")
        title = m.group("title").strip()

        if _is_bad_heading_candidate(title):
            return None

        # Reject decimal measurements like "1.415 MW ..."
        # True legal headings are usually "1.41." or "18.10."
        parts = num.split(".")
        first_word = title.split()[0].strip(".,;:()[]").upper() if title.split() else ""

        measurement_units = {
            "MW", "MWH", "KW", "KWH", "KV", "KVA", "VAC", "VDC", "AC", "DC"
        }

        if (
            not raw_num.endswith(".")
            and len(parts) == 2
            and len(parts[1]) >= 3
        ):
            return None

        if first_word in measurement_units:
            return None

        return {
            "kind": "numeric_clause",
            "level": num.count(".") + 1,
            "number": num,
            "nodeType": "clause",
            "title": clean,
        }

    m = NUMERIC_TOP_RE.match(clean)
    if m:
        num = m.group("num")
        title = m.group("title").strip()

        if _is_bad_heading_candidate(title):
            return None

        return {
            "kind": "numeric_top",
            "level": 1,
            "number": num,
            "nodeType": "section",
            "title": clean,
        }

    return None


def _candidate_counts(lines: List[str]) -> Dict[str, int]:
    counts = {
        "article": 0,
        "numeric_top": 0,
        "numeric_clause": 0,
        "exhibit": 0,
        "appendix": 0,
        "section_word": 0,
    }

    for line in lines:
        if _looks_like_toc_line(line):
            continue

        h = _detect_heading(line)

        if not h:
            continue

        kind = h["kind"]

        if kind in {"article"}:
            counts["article"] += 1
        elif kind == "numeric_top":
            counts["numeric_top"] += 1
        elif kind == "numeric_clause":
            counts["numeric_clause"] += 1
        elif kind == "exhibit":
            counts["exhibit"] += 1
        elif kind == "appendix":
            counts["appendix"] += 1
        elif kind == "section_word":
            counts["section_word"] += 1

    return counts


def _classify_contract_style(lines: List[str], raw_text: str) -> str:
    counts = _candidate_counts(lines)

    meaningful_text = re.sub(r"\[PAGE\s+\d+\]", "", raw_text, flags=re.IGNORECASE).strip()

    # ITEM-like case: only page markers / no extracted text
    if len(meaningful_text) < 2000 and not any(counts.values()):
        return "extraction_issue"

    # ARTICLE-heavy contracts: Edison, NextEra, NYISO, Terra, SoCal after splitting
    if counts["article"] >= 5:
        return "article"

    # Numeric + exhibit contracts: Sunpower, Solar
    if counts["numeric_top"] >= 3 and counts["exhibit"] >= 3:
        return "numeric_with_exhibits"

    # Numeric contracts: LFGTE
    if counts["numeric_top"] >= 5 and counts["numeric_clause"] >= 5:
        return "numeric"

    if counts["section_word"] >= 5:
        return "section_word"

    return "mixed"


def _first_word_after_number(title: str) -> str:
    m = re.match(r"^\d+(?:\.\d+)*\.?\s+([A-Za-z]+)", title.strip())
    return m.group(1) if m else ""


def _is_probable_list_item(candidate: Dict[str, Any]) -> bool:
    title = candidate.get("title", "")
    word = _first_word_after_number(title)

    if not word:
        return False

    # Lowercase after number usually means list item:
    # "1. has a first point..."
    if word and word[0].islower():
        return True

    return False


def _adjust_candidate_for_style(
    candidate: Dict[str, Any],
    style: str,
    current_top_kind: Optional[str],
) -> Optional[Dict[str, Any]]:
    """
    Converts candidate level/kind depending on document strategy.
    """

    cand = dict(candidate)
    kind = cand["kind"]

    # Universal top-level structural nodes
    if kind in {"article", "exhibit", "appendix", "schedule"}:
        cand["level"] = 1
        cand["nodeType"] = "section"
        return cand

    if style == "article":
        # In ARTICLE style, numeric clauses belong under current ARTICLE.
        if kind == "numeric_clause":
            return cand

        # Numeric top lines under ARTICLE can be list/clauses, not root sections.
        # Example Terra "1. has..." should be rejected.
        # Example Edison exhibit list "1. Con Edison..." can be child clause.
        if kind == "numeric_top":
            if _is_probable_list_item(cand):
                return None

            cand["level"] = 2
            cand["nodeType"] = "clause"
            return cand

        if kind == "section_word":
            cand["level"] = max(2, cand["level"])
            cand["nodeType"] = "clause"
            return cand

        return None

    if style in {"numeric", "numeric_with_exhibits", "mixed", "section_word"}:
        if kind == "numeric_top":
            # If currently inside exhibit/appendix, numeric top becomes child.
            if current_top_kind in {"exhibit", "appendix", "schedule"}:
                cand["level"] = 2
                cand["nodeType"] = "clause"
            else:
                cand["level"] = 1
                cand["nodeType"] = "section"
            return cand

        if kind == "numeric_clause":
            return cand

        if kind == "section_word":
            return cand

        return None

    return None


def _normalize_title_key(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().upper())


def _is_mergeable_top_level(title: str) -> bool:
    upper = (title or "").strip().upper()
    return (
        upper.startswith("ARTICLE ")
        or upper.startswith("EXHIBIT ")
        or upper.startswith("APPENDIX ")
        or upper.startswith("SCHEDULE ")
    )


def _merge_duplicate_top_level_structural_nodes(root: TreeNode) -> None:
    seen = {}
    merged_children = []

    for child in root.children:
        title = child.title or ""

        if not _is_mergeable_top_level(title):
            merged_children.append(child)
            continue

        key = _normalize_title_key(title)

        if key not in seen:
            seen[key] = child
            merged_children.append(child)
            continue

        existing = seen[key]

        # Merge text
        if child.text:
            existing.text = ((existing.text or "") + "\n" + child.text).strip()

        # Merge children
        for grandchild in child.children:
            grandchild.parentNodeId = existing.nodeId
            existing.children.append(grandchild)

        # Merge page ranges
        if child.pageStart is not None:
            if existing.pageStart is None:
                existing.pageStart = child.pageStart
            else:
                existing.pageStart = min(existing.pageStart, child.pageStart)

        if child.pageEnd is not None:
            if existing.pageEnd is None:
                existing.pageEnd = child.pageEnd
            else:
                existing.pageEnd = max(existing.pageEnd, child.pageEnd)

    root.children = merged_children

def _looks_like_heading_continuation(title: str) -> bool:
    clean = (title or "").strip()
    upper = clean.upper()

    if not clean:
        return False

    # Do not merge real structural headings.
    # Allow "SCHEDULE OF WORK" to merge because it can be a continuation title.
    if upper.startswith(("ARTICLE ", "EXHIBIT ", "APPENDIX ")):
        return False

    # All-caps continuation line, e.g. "SCHEDULE OF WORK"
    if re.match(r"^[A-Z][A-Z0-9 ,;/&()'\-]{4,120}$", clean):
        return True

    return False


def _merge_heading_continuation_nodes(root: TreeNode) -> None:
    """
    Merges split heading continuation nodes like:
    15. CLAIMS; CHANGE(S) TO SCOPE OF WORK OR
    SCHEDULE OF WORK

    into:
    15. CLAIMS; CHANGE(S) TO SCOPE OF WORK OR SCHEDULE OF WORK
    """

    merged_children = []
    i = 0

    while i < len(root.children):
        child = root.children[i]

        if (
            i + 1 < len(root.children)
            and child.title
            and child.title.strip().upper().endswith((" OR", " AND", " OF", " TO"))
        ):
            nxt = root.children[i + 1]

            if _looks_like_heading_continuation(nxt.title):
                child.title = f"{child.title.strip()} {nxt.title.strip()}"

                if nxt.text:
                    child.text = ((child.text or "") + "\n" + nxt.text).strip()

                for grandchild in nxt.children:
                    grandchild.parentNodeId = child.nodeId
                    child.children.append(grandchild)

                if nxt.pageEnd is not None:
                    child.pageEnd = max(child.pageEnd or nxt.pageEnd, nxt.pageEnd)

                merged_children.append(child)
                i += 2
                continue

        merged_children.append(child)
        i += 1

    root.children = merged_children

def build_fallback_tree(text: str, contract_id: str) -> TreeNode:
    preprocessed = _preprocess_text(text)

    raw_lines = preprocessed.splitlines()
    lines_for_profile = [l.strip() for l in raw_lines if l.strip()]
    style = _classify_contract_style(lines_for_profile, preprocessed)
    print(f"[TreeBuilder] contract_id={contract_id}, style={style}")
    
    root = TreeNode(
        nodeId=f"doc_{contract_id}",
        nodeType="document",
        title=contract_id,
        text="",
        pageStart=1,
        pageEnd=1,
        sourcePath=contract_id,
        children=[],
    )

    current_page = 1
    current = root
    buffer: List[str] = []
    level_nodes: Dict[int, TreeNode] = {0: root}
    current_top_kind: Optional[str] = None
    last_root_numeric_num: Optional[int] = None

    body_started = False

    in_toc = False
    toc_line_count = 0

    def flush():
        nonlocal buffer, current
        if buffer:
            content = "\n".join(buffer).strip()
            if content:
                current.text = ((current.text or "") + "\n" + content).strip()
                current.pageEnd = current_page
            buffer = []

    # If OCR/extraction issue, do not pretend to parse.
    if style == "extraction_issue":
        root.children = [
            TreeNode(
                nodeId=f"section_{contract_id}_full_document",
                nodeType="section",
                title="Full Document",
                text=text.strip(),
                parentNodeId=root.nodeId,
                pageStart=1,
                pageEnd=1,
                sourcePath=f"{contract_id} > Full Document",
                children=[],
            )
        ]
        return root

    for raw in raw_lines:
        line = raw.strip()

        page_match = PAGE_RE.match(line)
        if page_match:
            current_page = int(page_match.group(1))
            continue

        if not line:
            continue

        if _is_noise_line(line):
            continue

        # TOC handling
        if "TABLE OF CONTENTS" in line.upper():
            in_toc = True
            toc_line_count = 0
            continue

        if in_toc:
            toc_line_count += 1

            # Leave TOC when body-like non-TOC heading appears after enough lines.
            h = _detect_heading(line)
            if h and toc_line_count > 5 and not _looks_like_toc_line(line):
                in_toc = False
            else:
                continue

        if _looks_like_toc_line(line):
            continue

        candidate = _detect_heading(line)

        if candidate:
            candidate = _adjust_candidate_for_style(candidate, style, current_top_kind)

        if candidate:
            kind = candidate["kind"]

            # In numeric-style contracts, only allow root numeric sections in sequence.
            # Example valid root sequence: 1, 2, 3, ..., 25
            # Reject false roots like "366. Each Party..." after Section 25.
            if (
                style in {"numeric", "numeric_with_exhibits"}
                and kind == "numeric_top"
                and candidate["level"] == 1
            ):
                try:
                    current_num = int(candidate.get("number"))
                except Exception:
                    current_num = None

                if current_num is not None:
                    if last_root_numeric_num is None:
                        # First numeric section should usually be 1.
                        if current_num != 1:
                            candidate = None
                    else:
                        expected_next = last_root_numeric_num + 1

                        # Allow only normal next root section.
                        # This rejects false roots like 366. or restarted exhibit numbering.
                        if current_num != expected_next:
                            candidate = None

            if candidate is None:
                buffer.append(raw)
                continue

            kind = candidate["kind"]

            is_body_start = (
                kind in {"article", "exhibit", "appendix", "schedule"}
                or style in {"numeric", "numeric_with_exhibits", "mixed", "section_word"}
            )

            if is_body_start:
                body_started = True

            if not body_started:
                buffer.append(raw)
                continue

            flush()

            level = candidate["level"]
            node_type = candidate["nodeType"]
            title = candidate["title"]

            # Update top kind on top-level nodes.
            if level == 1:
                current_top_kind = kind

            if level == 1 and kind == "numeric_top":
                try:
                    last_root_numeric_num = int(candidate.get("number"))
                except Exception:
                    pass

            parent_level_candidates = [
                lvl for lvl in level_nodes.keys()
                if lvl < level
            ]

            parent_level = max(parent_level_candidates) if parent_level_candidates else 0
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
                children=[],
            )

            parent.children.append(node)

            level_nodes[level] = node

            for deeper in [lvl for lvl in list(level_nodes.keys()) if lvl > level]:
                del level_nodes[deeper]

            current = node

        else:
            buffer.append(raw)

    flush()

    root.pageEnd = current_page

    has_text_nodes = any(
        (n.text or "").strip()
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
                children=[],
            )
        ]

    _merge_heading_continuation_nodes(root)
    _merge_duplicate_top_level_structural_nodes(root)
    normalize_tree(root, None, [])

    return root


def flatten_tree(root: TreeNode) -> List[TreeNode]:
    out: List[TreeNode] = []

    def walk(n: TreeNode):
        out.append(n)
        for c in n.children:
            walk(c)

    walk(root)
    return out


def load_pageindex_tree(path: str, contract_id: str) -> TreeNode:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    # Self-hosted PageIndex output:
    # {"doc_name": "...", "structure": [...]}
    if isinstance(raw, dict) and "structure" in raw:
        root = TreeNode(
            nodeId=f"doc_{contract_id}",
            nodeType="document",
            title=raw.get("doc_name") or contract_id,
            text="",
            pageStart=1,
            pageEnd=None,
            sourcePath=contract_id,
            children=[
                _tree_node_from_any(child, contract_id)
                for child in raw.get("structure", [])
            ],
        )

    elif isinstance(raw, dict) and "tree" in raw:
        root = _tree_node_from_any(raw["tree"], contract_id=contract_id)

    elif isinstance(raw, dict) and "root" in raw:
        root = _tree_node_from_any(raw["root"], contract_id=contract_id)

    else:
        root = _tree_node_from_any(raw, contract_id=contract_id)

    if not root.nodeId:
        root.nodeId = f"doc_{contract_id}"

    if not root.title or root.title == "Untitled":
        root.title = contract_id

    root.nodeType = root.nodeType or "document"

    normalize_tree(root, None, [])

    return root
