import re
from pathlib import Path

SAFE_ID_RE = re.compile(r'[^a-zA-Z0-9_\-]+')

def safe_id(value: str) -> str:
    v = SAFE_ID_RE.sub('_', value.strip())
    return v.strip('_') or 'contract'

def contract_id_from_file(path: str) -> str:
    return safe_id(Path(path).stem)
