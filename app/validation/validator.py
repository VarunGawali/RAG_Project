import json
from pathlib import Path
from typing import Dict

REQUIRED_INDEX_FIELDS = ['id', 'contractId', 'itemType', 'nodeId', 'title', 'text', 'sourcePath']

def validate_processed_dir(processed_dir: str) -> Dict:
    p = Path(processed_dir)
    errors = []
    contract_count = 0
    doc_count = 0
    for cdir in [x for x in p.iterdir() if x.is_dir()] if p.exists() else []:
        contract_count += 1
        for name in ['raw_text.txt', 'tree.json', 'chunks.json', 'index_docs.json', 'manifest.json']:
            if not (cdir / name).exists():
                errors.append(f'{cdir.name}: missing {name}')
        index_path = cdir / 'index_docs.json'
        if index_path.exists():
            docs = json.loads(index_path.read_text(encoding='utf-8'))
            doc_count += len(docs)
            for i, d in enumerate(docs):
                for f in REQUIRED_INDEX_FIELDS:
                    if f not in d or d[f] in (None, ''):
                        errors.append(f'{cdir.name}: index doc {i} missing {f}')
                if not isinstance(d.get('embedding'), list) or not d.get('embedding'):
                    errors.append(f'{cdir.name}: index doc {i} missing embedding')
    return {'valid': not errors, 'contractCount': contract_count, 'indexDocCount': doc_count, 'errors': errors[:100]}
