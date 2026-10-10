"""OCR with Document AI (OCR processor in the `eu` location)."""

from google.api_core.client_options import ClientOptions
from google.cloud import documentai_v1 as documentai

PAGE_SEPARATOR = "\n\n"


def client(location: str = "eu", **kwargs) -> documentai.DocumentProcessorServiceClient:
    options = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    return documentai.DocumentProcessorServiceClient(client_options=options, **kwargs)


def ocr_pages(
    ocr_client: documentai.DocumentProcessorServiceClient,
    processor: str,
    pages: list[tuple[bytes, str]],
) -> str:
    """`pages`: (content, mime type) per uploaded file, in order. Errors propagate."""
    texts = []
    for content, mime_type in pages:
        result = ocr_client.process_document(
            request=documentai.ProcessRequest(
                name=processor,
                raw_document=documentai.RawDocument(content=content, mime_type=mime_type),
            )
        )
        texts.append(result.document.text.strip())
    return PAGE_SEPARATOR.join(texts)
