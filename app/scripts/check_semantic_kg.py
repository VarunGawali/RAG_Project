from app.kg.gremlin_writer import GremlinWriter
from app.kg.legal_extractor import LEGAL_NODE_TYPES, LEGAL_RELATIONSHIP_TYPES


def main():
    writer = GremlinWriter()

    try:
        total = writer.submit("g.V().has('nodeType', 'legal_entity').count()")
        print(f"\n{'='*45}")
        print(f"  Total semantic vertices : {total}")
        print(f"{'='*45}")

        print("\n--- Entity types ---")
        for label in LEGAL_NODE_TYPES:
            count = writer.submit(f"g.V().hasLabel('{label}').count()")
            if count and count[0] > 0:
                print(f"  {label:<30} {count[0]}")

        print("\n--- Relationship types ---")
        edge_labels = LEGAL_RELATIONSHIP_TYPES + ["EXTRACTED_ENTITY", "IMPOSES_OBLIGATION_ON"]
        for label in edge_labels:
            count = writer.submit(f"g.E().hasLabel('{label}').count()")
            if count and count[0] > 0:
                print(f"  {label:<35} {count[0]}")

        print(f"\n{'='*45}\n")

    finally:
        writer.close()


if __name__ == "__main__":
    main()