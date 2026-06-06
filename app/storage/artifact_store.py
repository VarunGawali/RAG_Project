import json
from pathlib import Path
from typing import Any, Dict, List, Union
from app import config

class ArtifactStore:
    def __init__(self, processed_dir: Path = config.PROCESSED_DIR):
        self.processed_dir = processed_dir
        self.processed_dir.mkdir(parents=True, exist_ok=True)

    def contract_dir(self, contract_id: str) -> Path:
        p = self.processed_dir / contract_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save_contract_artifacts(self, contract_id: str, raw_text: str, tree: Dict, chunks: List[Dict], index_docs: List[Dict], source_file: str) -> Dict:
        cdir = self.contract_dir(contract_id)
        (cdir / 'raw_text.txt').write_text(raw_text, encoding='utf-8')
        self._write_json(cdir / 'tree.json', tree)
        self._write_json(cdir / 'chunks.json', chunks)
        self._write_json(cdir / 'index_docs.json', index_docs)
        preview_docs = []
        for d in index_docs:
            preview = dict(d)
            preview.pop("embedding", None)

            text = preview.get("text", "")
            preview["textPreview"] = text[:700]
            preview.pop("text", None)

            preview_docs.append(preview)

        self._write_json(cdir / "index_docs_preview.json", preview_docs)
        manifest = {
            'contractId': contract_id,
            'sourceFile': source_file,
            'rawTextPath': str(cdir / 'raw_text.txt'),
            'treePath': str(cdir / 'tree.json'),
            'chunksPath': str(cdir / 'chunks.json'),
            'indexDocsPath': str(cdir / 'index_docs.json'),
            'chunkCount': len(chunks),
            'indexDocCount': len(index_docs),
            'indexDocsPreviewPath': str(cdir / 'index_docs_preview.json'),
        }
        self._write_json(cdir / 'manifest.json', manifest)
        return manifest

    def rebuild_corpus_files(self) -> Dict:
        manifests = []
        corpus_docs = []
        for cdir in sorted([p for p in self.processed_dir.iterdir() if p.is_dir()]):
            manifest_path = cdir / 'manifest.json'
            index_path = cdir / 'index_docs.json'
            if manifest_path.exists():
                manifests.append(json.loads(manifest_path.read_text(encoding='utf-8')))
            if index_path.exists():
                corpus_docs.extend(json.loads(index_path.read_text(encoding='utf-8')))
        corpus_manifest = {
            'contractCount': len(manifests),
            'indexDocCount': len(corpus_docs),
            'contracts': manifests,
        }
        self._write_json(self.processed_dir / 'corpus_manifest.json', corpus_manifest)
        self._write_json(self.processed_dir / 'corpus_index_docs.json', corpus_docs)
        return corpus_manifest

    def _write_json(self, path: Path, data: Any) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def get_artifact_store() -> Union["ArtifactStore", "BlobArtifactStore"]:
    """
    Return the appropriate artifact store based on configuration.

    USE_BLOB_ARTIFACTS=true  → BlobArtifactStore (Azure Blob, no local disk)
    USE_BLOB_ARTIFACTS=false → ArtifactStore     (local disk, for dev/testing)
    """
    if config.USE_BLOB_ARTIFACTS:
        from app.storage.blob_artifact_store import BlobArtifactStore
        return BlobArtifactStore()
    return ArtifactStore()


# Type alias for callers that want to hint the return type
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.storage.blob_artifact_store import BlobArtifactStore
