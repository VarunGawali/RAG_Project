from app.kg.gremlin_writer import GremlinWriter


def main():
    query = """
    g.V().
      hasLabel('Clause').
      as('clause').
      out('EXTRACTED_ENTITY').
      hasLabel('Obligation').
      as('obligation').
      select('clause', 'obligation').
      by(valueMap('title', 'pageStart', 'pageEnd', 'sourcePath')).
      by(valueMap('name', 'confidence', 'evidenceQuote'))
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