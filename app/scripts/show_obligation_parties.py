from app.kg.gremlin_writer import GremlinWriter


def first_value(prop_map, key, default=None):
    """
    Cosmos Gremlin valueMap returns values as lists.
    Example: {'name': ['Con Edison']}
    """
    value = prop_map.get(key, default)

    if isinstance(value, list):
        return value[0] if value else default

    return value


def main():
    writer = GremlinWriter()

    try:
        obligations_query = """
        g.V().
          hasLabel('Obligation').
          project('id', 'name', 'confidence', 'sourceClauseId').
            by(id()).
            by(values('name').fold()).
            by(values('confidence').fold()).
            by(values('sourceClauseId').fold())
        """

        obligations = writer.submit(obligations_query)

        if not obligations:
            print("No obligations found.")
            return

        print(f"Found {len(obligations)} obligations.")

        for idx, obligation in enumerate(obligations, start=1):
            obligation_id = obligation.get("id")
            obligation_name = first_value(obligation, "name", "unknown")
            confidence = first_value(obligation, "confidence", None)
            source_clause_id = first_value(obligation, "sourceClauseId", None)

            owed_by_query = """
            g.V(oid).
              out('OWED_BY').
              hasLabel('Party').
              valueMap('name')
            """

            owed_to_query = """
            g.V(oid).
              out('OWED_TO').
              hasLabel('Party').
              valueMap('name')
            """

            owed_by = writer.submit(owed_by_query, {"oid": obligation_id})
            owed_to = writer.submit(owed_to_query, {"oid": obligation_id})

            owed_by_names = [
                first_value(p, "name", "unknown")
                for p in owed_by
            ]

            owed_to_names = [
                first_value(p, "name", "unknown")
                for p in owed_to
            ]

            print("\n" + "=" * 80)
            print(f"Obligation {idx}")
            print("ID:", obligation_id)
            print("Name:", obligation_name)
            print("Confidence:", confidence)
            print("Source Clause:", source_clause_id)
            print("Owed By:", owed_by_names if owed_by_names else "Not found")
            print("Owed To:", owed_to_names if owed_to_names else "Not found")

    finally:
        writer.close()


if __name__ == "__main__":
    main()