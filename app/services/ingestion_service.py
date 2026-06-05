from pathlib import Path
from app.models import TreeNode
from typing import Dict, Optional
from app.readers.document_reader import read_document
from app.tree.tree_builder import build_fallback_tree, load_pageindex_tree
from app.chunking.chunker import create_chunks
from app.indexing.index_builder import IndexBuilder
from app.storage.artifact_store import ArtifactStore
from app.utils import contract_id_from_file
from app import config
from app.models import TreeNode
from app.pageindex.pageindex_api import PageIndexApiTreeGenerator

class IngestionService:
    def __init__(self):
        self.index_builder = IndexBuilder()
        self.store = ArtifactStore()

    def ingest_file(
        self,
        file_path: str,
        contract_id: Optional[str] = None,
        pageindex_json: Optional[str] = None
    ) -> Dict:
        contract_id = contract_id or contract_id_from_file(file_path)

        raw_text = read_document(file_path)

        tree = None

        # 1. Explicit PageIndex JSON
        if pageindex_json:
            print(f"[Ingestion] Using provided PageIndex JSON for {contract_id}")
            tree = load_pageindex_tree(pageindex_json, contract_id)

        # 2. Existing generated PageIndex JSON
        elif config.USE_PAGEINDEX_API:
            pageindex = PageIndexApiTreeGenerator()

            if pageindex.exists(contract_id):
                print(f"[Ingestion] Using cached PageIndex tree for {contract_id}")
                tree = load_pageindex_tree(str(pageindex.output_path(contract_id)), contract_id)

            else:
                print(f"[Ingestion] Generating PageIndex tree for {contract_id}")
                generated_path = pageindex.generate(file_path, contract_id)

                if generated_path:
                    tree = load_pageindex_tree(generated_path, contract_id)

        # 3. Fallback tree
        if tree is None:
            print(f"[Ingestion] Using fallback tree builder for {contract_id}")
            tree = build_fallback_tree(raw_text, contract_id)

        chunks = create_chunks(contract_id, tree)

        # 4. Final robust fallback
        if not chunks and raw_text.strip():
            print(f"[Ingestion] No chunks created for {contract_id}; using full-document fallback.")

            tree = TreeNode(
                nodeId=f"doc_{contract_id}",
                nodeType="document",
                title=contract_id,
                text="",
                pageStart=1,
                pageEnd=1,
                sourcePath=contract_id,
                children=[
                    TreeNode(
                        nodeId=f"section_{contract_id}_full_document",
                        nodeType="section",
                        title="Full Document",
                        text=raw_text.strip(),
                        parentNodeId=f"doc_{contract_id}",
                        pageStart=1,
                        pageEnd=1,
                        sourcePath=f"{contract_id} > Full Document",
                        children=[]
                    )
                ]
            )

            chunks = create_chunks(contract_id, tree)

        index_docs = self.index_builder.chunks_to_index_docs(chunks)

        manifest = self.store.save_contract_artifacts(
            contract_id=contract_id,
            raw_text=raw_text,
            tree=tree.to_dict(),
            chunks=[c.to_dict() for c in chunks],
            index_docs=index_docs,
            source_file=file_path,
        )

        corpus = self.store.rebuild_corpus_files()

        return {
            "manifest": manifest,
            "corpus": corpus
        }

    def ingest_folder(self, folder: str, pageindex_folder: Optional[str] = None) -> Dict:
        folder_path = Path(folder)
        if not folder_path.exists():
            raise FileNotFoundError(folder)
        supported = sorted([p for p in folder_path.iterdir() if p.suffix.lower() in {'.pdf', '.txt', '.md'}])
        results = []
        for file in supported:
            contract_id = contract_id_from_file(str(file))
            pageindex_json = None
            if pageindex_folder:
                candidate = Path(pageindex_folder) / f'{contract_id}.json'
                if candidate.exists():
                    pageindex_json = str(candidate)
            results.append(self.ingest_file(str(file), contract_id=contract_id, pageindex_json=pageindex_json)['manifest'])
        corpus = self.store.rebuild_corpus_files()
        return {'processedFiles': len(results), 'contracts': results, 'corpus': corpus}
