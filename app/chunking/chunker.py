import uuid
from typing import Dict, List
from app import config
from app.models import Chunk, TreeNode
from app.tree.tree_builder import flatten_tree

def infer_clause_type(text: str) -> str:
    t = text.lower()
    mapping = {
        'termination': ['terminate', 'termination', 'convenience', 'cause', 'expiry', 'expiration'],
        'payment': ['payment', 'invoice', 'fees', 'tax', 'late payment'],
        'liability': ['liability', 'damages', 'cap', 'limitation'],
        'confidentiality': ['confidential', 'confidentiality', 'non-disclosure'],
        'indemnity': ['indemnity', 'indemnify', 'indemnification'],
        'assignment': ['assign', 'assignment', 'transfer'],
        'governing_law': ['governing law', 'jurisdiction', 'venue'],
        'notice': ['notice', 'written notice'],
        'renewal': ['renewal', 'auto-renew', 'renew'],
    }
    for label, keys in mapping.items():
        if any(k in t for k in keys):
            return label
    return 'general'

def split_words(text: str, max_words: int, overlap: int) -> List[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text.strip()] if text.strip() else []
    chunks = []
    step = max(1, max_words - overlap)
    for start in range(0, len(words), step):
        part = words[start:start + max_words]
        if part:
            chunks.append(' '.join(part))
        if start + max_words >= len(words):
            break
    return chunks

def create_chunks(contract_id: str, root: TreeNode) -> List[Chunk]:
    nodes = flatten_tree(root)
    by_id: Dict[str, TreeNode] = {n.nodeId: n for n in nodes}
    chunks: List[Chunk] = []
    document_id = f'{contract_id}_doc'

    for node in nodes:
        if node.nodeType not in {'section', 'clause', 'paragraph', 'table', 'definition'}:
            continue
        if not node.text.strip():
            continue
        parts = split_words(node.text, config.CHUNK_MAX_WORDS, config.CHUNK_OVERLAP_WORDS)
        parent = by_id.get(node.parentNodeId or '')
        for i, part in enumerate(parts, start=1):
            item_type = f'{node.nodeType}_chunk'
            chunk_id = f'chunk_{contract_id}_{node.nodeId}_{i}_{uuid.uuid4().hex[:6]}'
            chunks.append(Chunk(
                id=chunk_id,
                contractId=contract_id,
                documentId=document_id,
                itemType=item_type,
                nodeId=node.nodeId,
                parentNodeId=node.parentNodeId,
                title=node.title,
                text=part,
                sectionTitle=node.title if node.nodeType == 'section' else (parent.title if parent else None),
                clauseTitle=node.title if node.nodeType == 'clause' else None,
                clauseType=infer_clause_type(node.title + ' ' + part),
                pageStart=node.pageStart,
                pageEnd=node.pageEnd,
                sourcePath=node.sourcePath,
                metadata={}
            ))
    return chunks
