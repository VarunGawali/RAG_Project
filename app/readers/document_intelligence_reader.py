from app import config

def read_with_document_intelligence(file_path: str) -> str:
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential

    if not config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT or not config.AZURE_DOCUMENT_INTELLIGENCE_KEY:
        raise RuntimeError('Azure Document Intelligence endpoint/key missing')

    client = DocumentIntelligenceClient(
        endpoint=config.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        credential=AzureKeyCredential(config.AZURE_DOCUMENT_INTELLIGENCE_KEY),
    )
    with open(file_path, 'rb') as f:
        poller = client.begin_analyze_document('prebuilt-layout', body=f)
    result = poller.result()

    lines = []
    for page in result.pages:
        lines.append(f'\n[PAGE {page.page_number}]')
        for line in page.lines or []:
            lines.append(line.content)
    return '\n'.join(lines)
