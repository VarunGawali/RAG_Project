from app import config
from app.readers.pdf_reader import read_document_local
from app.readers.document_intelligence_reader import read_with_document_intelligence

def read_document(file_path: str) -> str:
    if config.USE_AZURE_DOCUMENT_INTELLIGENCE:
        return read_with_document_intelligence(file_path)
    return read_document_local(file_path)
