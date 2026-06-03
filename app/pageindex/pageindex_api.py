import json
import time
from pathlib import Path
from typing import Optional

from app import config


class PageIndexApiTreeGenerator:
    """
    Uses hosted PageIndex API to generate a tree JSON for a PDF.

    Output:
      samples/pageindex_trees/{contract_id}.json
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or config.PAGEINDEX_OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def output_path(self, contract_id: str) -> Path:
        return self.output_dir / f"{contract_id}.json"

    def exists(self, contract_id: str) -> bool:
        return self.output_path(contract_id).exists()

    def generate(
        self,
        file_path: str,
        contract_id: str,
        force: bool = False
    ) -> Optional[str]:
        output_path = self.output_path(contract_id)

        if output_path.exists() and not force:
            print(f"[PageIndex] Existing tree found: {output_path}")
            return str(output_path)

        if not config.PAGEINDEX_API_KEY:
            print("[PageIndex] PAGEINDEX_API_KEY missing. Skipping PageIndex.")
            return None

        try:
            from app.pageindex import PageIndexClient
        except Exception as exc:
            print("[PageIndex] pageindex package not installed or import failed.")
            print(exc)
            return None

        print(f"[PageIndex] Submitting document: {file_path}")

        client = PageIndexClient(api_key=config.PAGEINDEX_API_KEY)

        try:
            submit_result = client.submit_document(file_path)
            doc_id = submit_result["doc_id"]
            print(f"[PageIndex] Submitted. doc_id={doc_id}")
        except Exception as exc:
            print("[PageIndex] submit_document failed.")
            print(exc)
            return None

        status = None

        for attempt in range(config.PAGEINDEX_MAX_POLLS):
            try:
                doc = client.get_document(doc_id)
                status = doc.get("status")

                print(
                    f"[PageIndex] Poll {attempt + 1}/"
                    f"{config.PAGEINDEX_MAX_POLLS}: status={status}"
                )

                if status == "completed":
                    break

                if status in {"failed", "error"}:
                    print("[PageIndex] Processing failed.")
                    return None

            except Exception as exc:
                print("[PageIndex] get_document failed.")
                print(exc)

            time.sleep(config.PAGEINDEX_POLL_SECONDS)

        if status != "completed":
            print("[PageIndex] Timed out waiting for processing.")
            return None

        try:
            tree_result = client.get_tree(doc_id)
            tree = tree_result.get("result", tree_result)
        except Exception as exc:
            print("[PageIndex] get_tree failed.")
            print(exc)
            return None

        output = {
            "provider": "pageindex_api",
            "doc_id": doc_id,
            "contractId": contract_id,
            "tree": tree
        }

        output_path.write_text(
            json.dumps(output, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

        print(f"[PageIndex] Tree saved: {output_path}")

        return str(output_path)