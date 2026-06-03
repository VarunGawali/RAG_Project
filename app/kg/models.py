from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class KGNode(BaseModel):
    kgId: str
    rawNodeId: str
    contractId: str
    tenantId: str

    nodeType: str
    label: str

    title: Optional[str] = None
    text: Optional[str] = None
    sectionNumber: Optional[str] = None

    pageStart: Optional[int] = None
    pageEnd: Optional[int] = None
    sourcePath: Optional[str] = None

    parentKgId: Optional[str] = None
    childrenKgIds: List[str] = Field(default_factory=list)
    siblingKgIds: List[str] = Field(default_factory=list)

    clauseTypeHint: Optional[str] = None
    extractionReady: bool = True

    properties: Dict[str, Any] = Field(default_factory=dict)


class KGEdge(BaseModel):
    edgeId: str
    sourceKgId: str
    targetKgId: str
    label: str
    tenantId: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class NormalizedContract(BaseModel):
    contractId: str
    tenantId: str
    nodes: List[KGNode]
    edges: List[KGEdge]


class LegalEntity(BaseModel):
    id: str
    type: str
    name: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    evidenceQuote: Optional[str] = None


class LegalRelationship(BaseModel):
    source_id: str
    target_id: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.0
    evidenceQuote: Optional[str] = None


class LegalExtractionResult(BaseModel):
    source_clause_id: str
    source_clause_title: Optional[str] = None
    source_page_start: Optional[int] = None
    source_page_end: Optional[int] = None

    entities: List[LegalEntity] = Field(default_factory=list)
    relationships: List[LegalRelationship] = Field(default_factory=list)