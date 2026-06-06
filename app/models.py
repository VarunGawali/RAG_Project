from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

@dataclass
class TreeNode:
    nodeId: str
    nodeType: str
    title: str
    text: str = ''
    parentNodeId: Optional[str] = None
    pageStart: Optional[int] = None
    pageEnd: Optional[int] = None
    sourcePath: Optional[str] = None
    children: List['TreeNode'] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d['children'] = [c.to_dict() for c in self.children]
        return d

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> 'TreeNode':
        return TreeNode(
            nodeId=d.get('nodeId') or d.get('id'),
            nodeType=d.get('nodeType') or d.get('type') or 'section',
            title=d.get('title') or d.get('heading') or d.get('name') or 'Untitled',
            text=d.get('text') or d.get('content') or '',
            parentNodeId=d.get('parentNodeId') or d.get('parentId'),
            pageStart=d.get('pageStart') or d.get('page_start') or d.get('page'),
            pageEnd=d.get('pageEnd') or d.get('page_end') or d.get('pageStart') or d.get('page'),
            sourcePath=d.get('sourcePath') or d.get('path'),
            children=[TreeNode.from_dict(c) for c in d.get('children', [])]
        )

@dataclass
class Chunk:
    id: str
    contractId: str
    documentId: str
    itemType: str
    nodeId: str
    parentNodeId: Optional[str]
    title: str
    text: str
    sectionTitle: Optional[str] = None
    clauseTitle: Optional[str] = None
    clauseType: str = 'general'
    pageStart: Optional[int] = None
    pageEnd: Optional[int] = None
    sourcePath: Optional[str] = None
    embedding: List[float] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
