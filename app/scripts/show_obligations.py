"""
Debug helper: list Obligation vertices and their denormalized citation
metadata directly from Gremlin.

Updated for the legal-only KG: obligations carry clauseTitle/pageStart/pageEnd
on the vertex itself (no structural Clause vertex / EXTRACTED_ENTITY edge).
"""

from app.kg.gremlin_writer import GremlinWriter


def main():
    query = """
    g.V().hasLabel('Obligation').dedup()
      .valueMap('name', 'contractId', 'confidence', 'evidenceQuote',
                'clauseTitle', 'pageStart', 'pageEnd')
    """

    writer = GremlinWriter()

    try:
        results = writer.submit(query)

        if not results:
            print("No obligations found.")
            return

        print(f"Found {len(results)} obligations.")

        for idx, item in enumerate(results, start=1):
            print("\n" + "=" * 80)
            print(f"Obligation {idx}")
            print(item)

    finally:
        writer.close()


if __name__ == "__main__":
    main()
