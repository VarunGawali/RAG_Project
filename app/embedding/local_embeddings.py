import hashlib
import math
import re
from typing import List
from app import config

TOKEN_RE = re.compile(r'[a-zA-Z0-9_\-]+')
STOPWORDS = {
    'the','a','an','this','that','is','are','was','were','to','of','in','on','for','with','and','or','by',
    'may','shall','will','can','could','would','agreement','contract','party','parties'
}
SYNONYMS = {
    'exit': ['terminate', 'termination'],
    'cancel': ['terminate', 'termination'],
    'end': ['terminate', 'termination'],
    'early': ['convenience', 'prior'],
    'cap': ['liability', 'limitation'],
    'damages': ['liability'],
    'pay': ['payment', 'invoice'],
    'money': ['payment', 'fees'],
    'risk': ['issue', 'problem'],
}

def tokenize(text: str) -> List[str]:
    base = [t.lower() for t in TOKEN_RE.findall(text or '') if len(t) > 2 and t.lower() not in STOPWORDS]
    expanded = list(base)
    for t in base:
        expanded.extend(SYNONYMS.get(t, []))
    return expanded

def local_embedding(text: str, dim: int = config.LOCAL_EMBEDDING_DIM) -> List[float]:
    vec = [0.0] * dim
    for token in tokenize(text):
        h = int(hashlib.md5(token.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0 if (h >> 8) % 2 == 0 else -1.0
    norm = math.sqrt(sum(x*x for x in vec)) or 1.0
    return [x / norm for x in vec]
