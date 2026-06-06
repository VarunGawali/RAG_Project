from app.kg.gremlin_writer import GremlinWriter


def main():
    query = """
    g.V().
      hasLabel('Obligation').
      as('obligation').
      out('HAS_DEADLINE').
      hasLabel('Deadline').
      as('deadline').
      select('obligation', 'deadline').
      by(valueMap('name', 'confidence', 'sourceClauseId')).
      by(valueMap('name', 'evidenceQuote'))
    """

    writer = GremlinWriter()

    try:
        results = writer.submit(query)

        if not results:
            print("No obligation-deadline relationships found.")
            return

        print(f"Found {len(results)} obligations with deadlines.")

        for idx, item in enumerate(results, start=1):
            print("\n" + "=" * 80)
            print(f"Deadline obligation {idx}")
            print(item)

    finally:
        writer.close()


if __name__ == "__main__":
    main()