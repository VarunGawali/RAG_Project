"""
Deterministic KG resolution pipeline (no LLM).

Rebuilds a clean two-tier semantic graph from saved extraction JSONs:

  Pass 1  ontology_normalizer  — slim ontology, label/edge drift, role→edge
  Pass 2  entity_resolver      — normalizedName, role-vs-named, per-contract de-frag
  Pass 3  canonicalizer        — global CanonicalEntity + RESOLVED_AS

See docs/kg_redesign_spec.md. These modules are pure-stdlib so the transform can
be run and audited locally without Azure / Gremlin / OpenAI config.
"""
