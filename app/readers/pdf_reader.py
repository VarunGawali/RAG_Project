from pathlib import Path

def read_pdf_local(file_path: str) -> str:
    from pypdf import PdfReader
    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ''
        pages.append(f'\n[PAGE {i}]\n{text}')
    return '\n'.join(pages)

def read_text_file(file_path: str) -> str:
    return Path(file_path).read_text(encoding='utf-8')

def read_document_local(file_path: str) -> str:
    suffix = Path(file_path).suffix.lower()
    if suffix == '.pdf':
        return read_pdf_local(file_path)
    if suffix in {'.txt', '.md'}:
        return read_text_file(file_path)
    raise ValueError(f'Unsupported file type: {suffix}. Use PDF/TXT/MD.')
