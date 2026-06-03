import argparse
from app.kg.gremlin_writer import GremlinWriter


LEGAL_VERTEX_LABELS = [
    "Party",
    "Obligation",
    "Right",
    "Restriction",
    "Condition",
    "Exception",
    "Deadline",
    "NoticePeriod",
    "Frequency",
    "MonetaryAmount",
    "Asset",
    "System",
    "Report",
    "Event",
    "RiskSignal",
]

LEGAL_EDGE_LABELS = [
    "EXTRACTED_ENTITY",
    "IMPOSES_OBLIGATION",
    "GRANTS_RIGHT",
    "PROHIBITS",
    "OWED_BY",
    "OWED_TO",
    "HELD_BY",
    "HAS_DEADLINE",
    "HAS_NOTICE_PERIOD",
    "HAS_FREQUENCY",
    "TRIGGERED_BY",
    "SUBJECT_TO",
    "EXCEPTS",
    "APPLIES_TO",
    "RECORDED_IN",
    "REQUIRES",
    "HAS_RISK_SIGNAL",
]


def count_vertices(writer: GremlinWriter, label: str):
    return writer.submit(f"g.V().hasLabel('{label}').count()")


def count_edges(writer: GremlinWriter, label: str):
    return writer.submit(f"g.E().hasLabel('{label}').count()")


def drop_edges(writer: GremlinWriter, label: str):
    return writer.submit(f"g.E().hasLabel('{label}').drop()")


def drop_vertices(writer: GremlinWriter, label: str):
    return writer.submit(f"g.V().hasLabel('{label}').drop()")


def main():
    parser = argparse.ArgumentParser("clear-semantic-kg")
    parser.add_argument(
        "--all",
        action="store_true",
        help="Clear all semantic labels. Recommended for current dev graph."
    )
    parser.add_argument(
        "--contract-id",
        required=False,
        help="Accepted for compatibility, but current cleanup clears semantic labels globally."
    )

    args = parser.parse_args()

    writer = GremlinWriter()

    try:
        print("Semantic vertex counts before clear:")
        for label in LEGAL_VERTEX_LABELS:
            print(f"  {label}: {count_vertices(writer, label)}")

        print("\nSemantic edge counts before clear:")
        for label in LEGAL_EDGE_LABELS:
            print(f"  {label}: {count_edges(writer, label)}")

        print("\nDropping semantic edges...")
        for label in LEGAL_EDGE_LABELS:
            print(f"  Dropping edge label: {label}")
            drop_edges(writer, label)

        print("\nDropping semantic vertices...")
        for label in LEGAL_VERTEX_LABELS:
            print(f"  Dropping vertex label: {label}")
            drop_vertices(writer, label)

        print("\nSemantic vertex counts after clear:")
        for label in LEGAL_VERTEX_LABELS:
            print(f"  {label}: {count_vertices(writer, label)}")

        print("\nSemantic edge counts after clear:")
        for label in LEGAL_EDGE_LABELS:
            print(f"  {label}: {count_edges(writer, label)}")

        print("\nSemantic KG cleared.")

    finally:
        writer.close()


if __name__ == "__main__":
    main()