from app.kg.gremlin_writer import GremlinWriter


def main():
    writer = GremlinWriter()

    queries = {
        "Total vertices": "g.V().count()",
        "Contracts": "g.V().hasLabel('Contract').count()",
        "Sections": "g.V().hasLabel('Section').count()",
        "Clauses": "g.V().hasLabel('Clause').count()",
        "Appendices": "g.V().hasLabel('Appendix').count()",
        "Exhibits": "g.V().hasLabel('Exhibit').count()",
        "Total edges": "g.E().count()",
        "CONTAINS_SECTION": "g.E().hasLabel('CONTAINS_SECTION').count()",
        "CONTAINS_CLAUSE": "g.E().hasLabel('CONTAINS_CLAUSE').count()",
        "HAS_PARENT": "g.E().hasLabel('HAS_PARENT').count()",
        "NEXT_SIBLING": "g.E().hasLabel('NEXT_SIBLING').count()",
        "PREVIOUS_SIBLING": "g.E().hasLabel('PREVIOUS_SIBLING').count()",
        "HAS_APPENDIX": "g.E().hasLabel('HAS_APPENDIX').count()",
        "HAS_EXHIBIT": "g.E().hasLabel('HAS_EXHIBIT').count()",
    }

    try:
        for label, query in queries.items():
            result = writer.submit(query)
            print(label, ":", result)
    finally:
        writer.close()


if __name__ == "__main__":
    main()