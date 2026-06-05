"""
Stage 2: Schema induction from open-ended discovery extractions.

Input:  discovery JSONs produced by discovery_extractor.py
        (one per contract, each containing raw entity/relationship type names)

Process:
  1. Collect all raw entity type names and relationship type names
  2. Embed them using Azure OpenAI embeddings
  3. Cluster semantically similar names (cosine similarity)
  4. Count frequency across contracts (how many of N contracts contain this type)
  5. Propose canonical name per cluster (ask LLM to pick the best legal term)
  6. Output Contract360 Legal Ontology v1 proposal JSON

Output: data/kg/schema_discovery/ontology_proposal.json
"""

import json
import re
import hashlib
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any

import numpy as np
from openai import AzureOpenAI

from app import config


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

SCHEMA_DISCOVERY_DIR = config.KG_DIR / "schema_discovery"
SCHEMA_DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value)
    return value.strip("_")


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


# ---------------------------------------------------------------------------
# Embedding client
# ---------------------------------------------------------------------------

def get_embeddings(texts: List[str], client: AzureOpenAI) -> List[np.ndarray]:
    """Embed a list of texts in batches of 100."""
    results: List[np.ndarray] = []
    batch_size = 100

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(
            model=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            input=batch,
        )
        for item in response.data:
            results.append(np.array(item.embedding, dtype=np.float32))

    return results


# ---------------------------------------------------------------------------
# Step 1: Load and collect raw type names from all discovery files
# ---------------------------------------------------------------------------

def load_discovery_files(discovery_dir: Path) -> List[Dict[str, Any]]:
    """Load all discovery extraction JSONs from a directory."""
    files = sorted(discovery_dir.glob("*_discovery.json"))

    if not files:
        raise FileNotFoundError(
            f"No discovery files found in {discovery_dir}. "
            "Run Stage 1 (run_discovery.py) first."
        )

    all_results = []
    for f in files:
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            all_results.extend(data if isinstance(data, list) else [data])

    print(f"Loaded {len(all_results)} clause extractions from {len(files)} files")
    return all_results


def collect_type_occurrences(
    results: List[Dict[str, Any]],
) -> Tuple[
    Dict[str, List[str]],   # entity_type_name -> [contract_ids]
    Dict[str, List[str]],   # relationship_type_name -> [contract_ids]
]:
    """
    Collect every raw type name and which contracts it appears in.
    Returns two maps: entity types and relationship types.
    """
    entity_type_to_contracts: Dict[str, List[str]] = defaultdict(list)
    rel_type_to_contracts: Dict[str, List[str]] = defaultdict(list)

    for result in results:
        contract_id = result.get("contract_id", "unknown")

        for ent in result.get("entities", []):
            raw_type = (ent.get("entity_type") or "").strip()
            if raw_type:
                entity_type_to_contracts[raw_type].append(contract_id)

        for rel in result.get("relationships", []):
            raw_type = (rel.get("relationship_type") or "").strip()
            if raw_type:
                rel_type_to_contracts[raw_type].append(contract_id)

    return dict(entity_type_to_contracts), dict(rel_type_to_contracts)


# ---------------------------------------------------------------------------
# Step 2: Cluster by embedding similarity
# ---------------------------------------------------------------------------

def cluster_by_similarity(
    type_names: List[str],
    embeddings: List[np.ndarray],
    threshold: float = 0.82,
) -> List[List[str]]:
    """
    Greedy agglomerative clustering by cosine similarity.

    Each cluster = group of type names that are semantically equivalent.
    threshold: names with cosine similarity >= threshold are grouped.

    Returns list of clusters, each cluster is a list of raw type names.
    """
    n = len(type_names)
    assigned = [-1] * n
    clusters: List[List[int]] = []

    for i in range(n):
        if assigned[i] >= 0:
            continue

        cluster_id = len(clusters)
        clusters.append([i])
        assigned[i] = cluster_id

        for j in range(i + 1, n):
            if assigned[j] >= 0:
                continue

            sim = cosine_similarity(embeddings[i], embeddings[j])
            if sim >= threshold:
                clusters[cluster_id].append(j)
                assigned[j] = cluster_id

    return [[type_names[idx] for idx in cluster] for cluster in clusters]


# ---------------------------------------------------------------------------
# Step 3: Canonicalization — frequency-first, single batched LLM polish
# ---------------------------------------------------------------------------

def to_pascal_case(name: str) -> str:
    """Convert 'cure period' or 'Cure Period' → 'CurePeriod'."""
    words = re.sub(r"[^a-zA-Z0-9 ]+", " ", name).split()
    return "".join(w.capitalize() for w in words if w)


BATCH_CANONICALIZE_SYSTEM = """You are a legal ontology expert specializing in contract law.
You will receive a JSON list of term groups. Each group has a "representative" name and
optional "aliases" (synonyms from the same semantic cluster).

━━━ YOUR TASK ━━━
For each group, return the single best canonical PascalCase legal ontology name and a
one-sentence definition.

━━━ CRITICAL RULES ━━━

1. POLARITY CHECK FIRST — Before canonicalizing any group, verify all members share
   the same legal polarity. Legally opposite roles must NEVER be in the same group.
   Known opposite pairs that must stay separate:
   • Indemnitor  ↔  Indemnitee
   • Obligor     ↔  Obligee
   • Buyer       ↔  Seller
   • Defaulting Party  ↔  Non-Defaulting Party
   • Breaching Party   ↔  Non-Breaching Party
   • Disclosing Party  ↔  Receiving Party
   • Assignor    ↔  Assignee
   If a group contains members from BOTH sides of a pair, set "split_required": true
   and list the two subgroups in "split_into".

2. LEGAL PRECISION — do not over-generalise. "CurePeriod" is better than "Period".
   "LiquidatedDamagesClause" is better than "DamagesProvision".

3. PASCAL CASE — e.g. CurePeriod, LiquidatedDamagesCap, ForceMAjeureEvent

4. NO COMPOUND TYPES — if the representative is "Indemnitor and Contracting Party",
   the canonical should be "Indemnitor" (drop the compound qualifier).

Return a JSON array in the same order:
[
  {"canonical": "CurePeriod", "definition": "..."},
  {"canonical": "Indemnitor", "definition": "...", "split_required": false},
  {
    "canonical": "SPLIT_NEEDED",
    "definition": "",
    "split_required": true,
    "split_into": [
      {"canonical": "Indemnitor", "definition": "Party bearing the indemnification obligation."},
      {"canonical": "Indemnitee", "definition": "Party protected by the indemnification obligation."}
    ]
  }
]"""


def canonicalize_clusters(
    entity_clusters: List[List[str]],
    rel_clusters: List[List[str]],
    client: AzureOpenAI,
    type_to_contracts_entity: Optional[Dict[str, List[str]]] = None,
    type_to_contracts_rel: Optional[Dict[str, List[str]]] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    Two-step canonicalization:
      1. For each cluster pick the most-frequent raw variant as representative
         (zero LLM calls for single-item clusters).
      2. For multi-item clusters only, send ONE batched LLM call per 50 clusters
         to get proper PascalCase legal names.
    """

    def pick_representative(cluster: List[str], freq_map: Optional[Dict[str, List[str]]]) -> str:
        """Pick the variant that appears in the most contracts; break ties by length."""
        if len(cluster) == 1:
            return cluster[0]
        if freq_map:
            return max(cluster, key=lambda t: (len(set(freq_map.get(t, []))), -len(t)))
        return max(cluster, key=lambda t: -len(t))  # shortest if no freq data

    def batch_llm_polish(
        clusters_with_rep: List[Tuple[List[str], str]],
        kind: str,
    ) -> List[Dict]:
        """
        Send groups to LLM in batches of 50.
        Only clusters with 2+ members get sent; single-item clusters
        are just PascalCase-converted locally.
        """
        proposals: List[Optional[Dict]] = [None] * len(clusters_with_rep)

        # Separate: single-item (no LLM) vs multi-item (needs LLM)
        single_indices = [i for i, (cl, _) in enumerate(clusters_with_rep) if len(cl) == 1]
        multi_indices  = [i for i, (cl, _) in enumerate(clusters_with_rep) if len(cl) > 1]

        # Single-item: local PascalCase, no definition needed yet
        for i in single_indices:
            cluster, rep = clusters_with_rep[i]
            proposals[i] = {
                "canonical": to_pascal_case(rep),
                "definition": "",
                "raw_variants": cluster,
            }

        # Multi-item: batch LLM call in groups of 50
        batch_size = 50
        for batch_start in range(0, len(multi_indices), batch_size):
            batch_idx = multi_indices[batch_start : batch_start + batch_size]
            payload = [
                {
                    "representative": clusters_with_rep[i][1],
                    "aliases": [v for v in clusters_with_rep[i][0] if v != clusters_with_rep[i][1]],
                }
                for i in batch_idx
            ]

            prompt = (
                f"These are {kind} term groups from legal contracts. "
                f"Return a JSON array of {len(payload)} objects.\n\n"
                + json.dumps(payload, indent=2)
            )

            try:
                response = client.chat.completions.create(
                    model=config.AZURE_OPENAI_CHAT_DEPLOYMENT,
                    temperature=0,
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": BATCH_CANONICALIZE_SYSTEM},
                        {"role": "user", "content": prompt},
                    ],
                )
                content = json.loads(response.choices[0].message.content)
                # LLM may return {"items": [...]} or just [...]
                items = content if isinstance(content, list) else content.get("items", content.get("results", []))
            except Exception as e:
                print(f"  [warn] LLM batch failed ({e}), falling back to local PascalCase")
                items = []

            for k, orig_i in enumerate(batch_idx):
                cluster, rep = clusters_with_rep[orig_i]
                item = items[k] if k < len(items) else {}

                if item.get("split_required") and item.get("split_into"):
                    # LLM detected a polarity error — emit one proposal per sub-group
                    # Each sub-group inherits the full cluster's raw_variants for now
                    # (frequency scoring will still work correctly)
                    print(f"  [split] cluster '{rep}' split into: "
                          f"{[s['canonical'] for s in item['split_into']]}")
                    for sub in item["split_into"]:
                        proposals.append({
                            "canonical": sub.get("canonical", to_pascal_case(rep)),
                            "definition": sub.get("definition", ""),
                            "raw_variants": cluster,   # shared — frequency still correct
                            "was_split": True,
                        })
                    proposals[orig_i] = None  # placeholder replaced by appended entries
                else:
                    proposals[orig_i] = {
                        "canonical": item.get("canonical") or to_pascal_case(rep),
                        "definition": item.get("definition", ""),
                        "raw_variants": cluster,
                    }

        return [p for p in proposals if p is not None]

    print(f"Canonicalizing {len(entity_clusters)} entity clusters "
          f"({sum(1 for c in entity_clusters if len(c) > 1)} need LLM)...")
    ent_pairs = [(cl, pick_representative(cl, type_to_contracts_entity)) for cl in entity_clusters]
    entity_proposals = batch_llm_polish(ent_pairs, "entity")

    print(f"Canonicalizing {len(rel_clusters)} relationship clusters "
          f"({sum(1 for c in rel_clusters if len(c) > 1)} need LLM)...")
    rel_pairs = [(cl, pick_representative(cl, type_to_contracts_rel)) for cl in rel_clusters]
    rel_proposals = batch_llm_polish(rel_pairs, "relationship")

    return entity_proposals, rel_proposals


# ---------------------------------------------------------------------------
# Step 4: Frequency scoring and prevalence labeling
# ---------------------------------------------------------------------------

def add_frequency_stats(
    proposals: List[Dict],
    type_to_contracts: Dict[str, List[str]],
    total_contracts: int,
) -> List[Dict]:
    """
    Attach frequency and prevalence to each canonical proposal.
    Frequency = number of distinct contracts where any variant appeared.
    """
    for proposal in proposals:
        variants = proposal.get("raw_variants", [])
        contract_set = set()

        for variant in variants:
            contracts = type_to_contracts.get(variant, [])
            contract_set.update(contracts)

        freq = len(contract_set)
        pct = round(freq / total_contracts * 100, 1) if total_contracts > 0 else 0.0

        if pct >= 80:
            prevalence = "universal"
        elif pct >= 50:
            prevalence = "common"
        elif pct >= 25:
            prevalence = "occasional"
        else:
            prevalence = "rare"

        proposal["frequency"] = freq
        proposal["frequency_pct"] = pct
        proposal["prevalence"] = prevalence
        proposal["appears_in_contracts"] = sorted(contract_set)

    # Sort by frequency descending
    proposals.sort(key=lambda x: x["frequency"], reverse=True)
    return proposals


# ---------------------------------------------------------------------------
# Step 5: Generate ontology proposal
# ---------------------------------------------------------------------------

ONTOLOGY_LAYER_RULES = {
    "universal":   "layer_1_universal",    # 80%+ contracts
    "common":      "layer_2_common",       # 50-79% contracts
    "occasional":  "layer_3_occasional",   # 25-49% contracts
    "rare":        "layer_4_rare",         # <25% contracts
}


def build_ontology_proposal(
    entity_proposals: List[Dict],
    rel_proposals: List[Dict],
    total_contracts: int,
) -> Dict[str, Any]:
    """
    Assemble the final ontology proposal JSON.

    Layer 1 (universal) → first-class vertex labels, use in all extractions
    Layer 2 (common)    → first-class vertex labels, use in all extractions
    Layer 3 (occasional)→ include in extraction but mark as specialized
    Layer 4 (rare)      → consider collapsing to properties, not vertices
    """
    entity_layers: Dict[str, List[Dict]] = defaultdict(list)
    rel_layers: Dict[str, List[Dict]] = defaultdict(list)

    for ep in entity_proposals:
        layer = ONTOLOGY_LAYER_RULES[ep["prevalence"]]
        entity_layers[layer].append({
            "canonical": ep["canonical"],
            "definition": ep.get("definition", ""),
            "aliases": ep.get("aliases", ep.get("raw_variants", [])),
            "frequency": ep["frequency"],
            "frequency_pct": ep["frequency_pct"],
            "appears_in_contracts": ep["appears_in_contracts"],
        })

    for rp in rel_proposals:
        layer = ONTOLOGY_LAYER_RULES[rp["prevalence"]]
        rel_layers[layer].append({
            "canonical": rp["canonical"],
            "definition": rp.get("definition", ""),
            "aliases": rp.get("aliases", rp.get("raw_variants", [])),
            "frequency": rp["frequency"],
            "frequency_pct": rp["frequency_pct"],
            "appears_in_contracts": rp["appears_in_contracts"],
        })

    # Flat lists for easy copy-paste into legal_extractor.py
    constrained_entity_types = [
        ep["canonical"]
        for ep in entity_proposals
        if ep["prevalence"] in {"universal", "common"}
    ]

    constrained_rel_types = [
        rp["canonical"]
        for rp in rel_proposals
        if rp["prevalence"] in {"universal", "common"}
    ]

    return {
        "metadata": {
            "total_contracts_analyzed": total_contracts,
            "total_raw_entity_types": sum(
                len(ep.get("aliases", ep.get("raw_variants", []))) for ep in entity_proposals
            ),
            "total_raw_rel_types": sum(
                len(rp.get("aliases", rp.get("raw_variants", []))) for rp in rel_proposals
            ),
            "canonical_entity_types": len(entity_proposals),
            "canonical_rel_types": len(rel_proposals),
        },
        "entity_types": dict(entity_layers),
        "relationship_types": dict(rel_layers),
        "constrained_extraction_schema": {
            "description": (
                "Copy these into LEGAL_NODE_TYPES and LEGAL_RELATIONSHIP_TYPES "
                "in legal_extractor.py for Stage 3 constrained extraction."
            ),
            "LEGAL_NODE_TYPES": constrained_entity_types,
            "LEGAL_RELATIONSHIP_TYPES": constrained_rel_types,
        },
    }


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_schema_induction(
    discovery_dir: Path,
    output_path: Optional[Path] = None,
    similarity_threshold: float = 0.72,
) -> Dict[str, Any]:
    """
    Full Stage 2 pipeline:
      1. Load discovery files
      2. Collect raw type names
      3. Embed
      4. Cluster
      5. Canonicalize
      6. Frequency scoring
      7. Build ontology proposal
    """
    client = AzureOpenAI(
        azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
        api_key=config.AZURE_OPENAI_API_KEY,
        api_version=config.AZURE_OPENAI_API_VERSION,
    )

    # Step 1: Load
    results = load_discovery_files(discovery_dir)
    total_contracts = len({r.get("contract_id", "unknown") for r in results})
    print(f"Total contracts: {total_contracts}")

    # Step 2: Collect raw types
    entity_type_to_contracts, rel_type_to_contracts = collect_type_occurrences(results)

    entity_type_names = sorted(entity_type_to_contracts.keys())
    rel_type_names = sorted(rel_type_to_contracts.keys())

    print(f"Unique raw entity types: {len(entity_type_names)}")
    print(f"Unique raw relationship types: {len(rel_type_names)}")

    # Step 3: Embed
    print("Embedding entity type names...")
    entity_embeddings = get_embeddings(entity_type_names, client)

    print("Embedding relationship type names...")
    rel_embeddings = get_embeddings(rel_type_names, client)

    # Step 4: Cluster
    print(f"Clustering entity types (threshold={similarity_threshold})...")
    entity_clusters = cluster_by_similarity(
        entity_type_names, entity_embeddings, threshold=similarity_threshold
    )

    print(f"Clustering relationship types (threshold={similarity_threshold})...")
    rel_clusters = cluster_by_similarity(
        rel_type_names, rel_embeddings, threshold=similarity_threshold
    )

    print(f"Entity clusters: {len(entity_clusters)} (from {len(entity_type_names)} raw types)")
    print(f"Relationship clusters: {len(rel_clusters)} (from {len(rel_type_names)} raw types)")

    # Step 5: Canonicalize via LLM (batched, single-items handled locally)
    entity_proposals, rel_proposals = canonicalize_clusters(
        entity_clusters, rel_clusters, client,
        type_to_contracts_entity=entity_type_to_contracts,
        type_to_contracts_rel=rel_type_to_contracts,
    )

    # Step 6: Frequency scoring
    entity_proposals = add_frequency_stats(
        entity_proposals, entity_type_to_contracts, total_contracts
    )
    rel_proposals = add_frequency_stats(
        rel_proposals, rel_type_to_contracts, total_contracts
    )

    # Step 7: Build ontology proposal
    ontology = build_ontology_proposal(entity_proposals, rel_proposals, total_contracts)

    # Save raw intermediate files for inspection
    raw_path = SCHEMA_DISCOVERY_DIR / "raw_type_occurrences.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "entity_types": {
                    k: sorted(set(v)) for k, v in entity_type_to_contracts.items()
                },
                "relationship_types": {
                    k: sorted(set(v)) for k, v in rel_type_to_contracts.items()
                },
            },
            f, indent=2, ensure_ascii=False,
        )

    clusters_path = SCHEMA_DISCOVERY_DIR / "clusters.json"
    with open(clusters_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "entity_clusters": entity_clusters,
                "relationship_clusters": rel_clusters,
            },
            f, indent=2, ensure_ascii=False,
        )

    # Save final ontology proposal
    if output_path is None:
        output_path = SCHEMA_DISCOVERY_DIR / "ontology_proposal.json"

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(ontology, f, indent=2, ensure_ascii=False)

    print(f"\nOntology proposal saved to: {output_path}")
    print(f"Raw type occurrences saved to: {raw_path}")
    print(f"Clusters saved to: {clusters_path}")

    return ontology