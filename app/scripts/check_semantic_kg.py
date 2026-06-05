from app.kg.gremlin_writer import GremlinWriter


def main():
    writer = GremlinWriter()

    queries = {
        "Legal entities": "g.V().has('nodeType', 'legal_entity').count()",
        "Obligations": "g.V().hasLabel('Obligation').count()",
        "Rights": "g.V().hasLabel('Right').count()",
        "Restrictions": "g.V().hasLabel('Restriction').count()",
        "Parties": "g.V().hasLabel('Party').count()",
        "Assets": "g.V().hasLabel('Asset').count()",
        "Events": "g.V().hasLabel('Event').count()",
        "Deadlines": "g.V().hasLabel('Deadline').count()",
        "NoticePeriods": "g.V().hasLabel('NoticePeriod').count()",
        "Frequencies": "g.V().hasLabel('Frequency').count()",
        "RiskSignals": "g.V().hasLabel('RiskSignal').count()",
        "EXTRACTED_ENTITY": "g.E().hasLabel('EXTRACTED_ENTITY').count()",
        "IMPOSES_OBLIGATION": "g.E().hasLabel('IMPOSES_OBLIGATION').count()",
        "GRANTS_RIGHT": "g.E().hasLabel('GRANTS_RIGHT').count()",
        "OWED_BY": "g.E().hasLabel('OWED_BY').count()",
        "OWED_TO": "g.E().hasLabel('OWED_TO').count()",
        "HAS_DEADLINE": "g.E().hasLabel('HAS_DEADLINE').count()",
        "HAS_FREQUENCY": "g.E().hasLabel('HAS_FREQUENCY').count()",
    }

    try:
        for label, query in queries.items():
            result = writer.submit(query)
            print(label, ":", result)
    finally:
        writer.close()


if __name__ == "__main__":
    main()