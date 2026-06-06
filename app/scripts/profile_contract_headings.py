import json
import re
from pathlib import Path
from collections import Counter, defaultdict

PROCESSED_DIR = Path("data/processed")

PATTERNS = {
    "article_roman": re.compile(r"^ARTICLE\s+[IVXLCDM]+\b.*$", re.IGNORECASE),
    "article_number": re.compile(r"^ARTICLE\s+\d+\b.*$", re.IGNORECASE),
    "section_word": re.compile(r"^SECTION\s+\d+(?:\.\d+)*\b.*$", re.IGNORECASE),
    "numeric_top": re.compile(r"^\d+\.?\s+[A-Z].*$"),
    "numeric_clause": re.compile(r"^\d+\.\d+(?:\.\d+)*\.?\s+.*$"),
    "appendix": re.compile(r"^APPENDIX\s+[A-Z0-9]+\b.*$", re.IGNORECASE),
    "exhibit": re.compile(r"^EXHIBIT\s+[A-Z0-9]+\b.*$", re.IGNORECASE),
    "schedule": re.compile(r"^SCHEDULE\s+[A-Z0-9]+\b.*$", re.IGNORECASE),
    "all_caps": re.compile(r"^[A-Z0-9][A-Z0-9 ,/&()'\-]{5,120}$"),
}

BAD_PATTERNS = {
    "page_footer": re.compile(r"\b\d+\s*\|\s*Page\b", re.IGNORECASE),
    "address": re.compile(r"\b(STREET|ST\.|ROAD|RD\.|AVENUE|AVE\.|PLACE|DRIVE|LANE|BLVD|NY|NEW YORK|BRANCH ROAD)\b", re.IGNORECASE),
    "email": re.compile(r"@"),
    "execution_copy": re.compile(r"EXECUTION COPY", re.IGNORECASE),
    "watermark": re.compile(r"ALL TERMS, CONDITIONS, AND RATES", re.IGNORECASE),
}


def classify_line(line: str):
    clean = line.strip()

    bad_hits = [
        name for name, pattern in BAD_PATTERNS.items()
        if pattern.search(clean)
    ]

    hits = [
        name for name, pattern in PATTERNS.items()
        if pattern.match(clean)
    ]

    return hits, bad_hits


def flatten_tree(root):
    nodes = []

    def walk(node):
        nodes.append(node)
        for child in node.get("children", []) or []:
            walk(child)

    walk(root)
    return nodes


def main():
    report = {}

    for contract_dir in sorted(PROCESSED_DIR.iterdir()):
        if not contract_dir.is_dir():
            continue

        raw_path = contract_dir / "raw_text.txt"
        tree_path = contract_dir / "tree.json"

        if not raw_path.exists():
            continue

        text = raw_path.read_text(encoding="utf-8", errors="ignore")
        lines = [l.strip() for l in text.splitlines() if l.strip()]

        pattern_counts = Counter()
        bad_counts = Counter()
        examples = defaultdict(list)

        for line in lines:
            hits, bad_hits = classify_line(line)

            for h in hits:
                pattern_counts[h] += 1
                if len(examples[h]) < 15:
                    examples[h].append(line)

            for b in bad_hits:
                bad_counts[b] += 1
                if len(examples[f"BAD_{b}"]) < 10:
                    examples[f"BAD_{b}"].append(line)

        tree_summary = {}

        if tree_path.exists():
            tree = json.loads(tree_path.read_text(encoding="utf-8"))
            nodes = flatten_tree(tree)
            children = tree.get("children", []) or []

            tree_summary = {
                "topLevelCount": len(children),
                "topLevelTitles": [c.get("title") for c in children[:40]],
                "nodeTypeCounts": dict(Counter(n.get("nodeType") for n in nodes)),
                "isFullDocumentFallback": (
                    len(children) == 1
                    and children[0].get("title") == "Full Document"
                ),
            }

        report[contract_dir.name] = {
            "lineCount": len(lines),
            "patternCounts": dict(pattern_counts),
            "badCounts": dict(bad_counts),
            "examples": dict(examples),
            "treeSummary": tree_summary,
        }

    output_path = Path("heading_profile_report.json")
    output_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print(f"Saved report: {output_path}")

    for contract_id, data in report.items():
        print("\n" + "=" * 100)
        print(contract_id)
        print("Pattern counts:", data["patternCounts"])
        print("Bad counts:", data["badCounts"])
        print("Tree:", data["treeSummary"])

        print("\nExamples:")
        for pattern_name, vals in data["examples"].items():
            print(f"\n[{pattern_name}]")
            for v in vals[:8]:
                print(" -", v)


if __name__ == "__main__":
    main()