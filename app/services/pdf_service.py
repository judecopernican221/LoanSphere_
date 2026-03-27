"""
PDF text extraction using PyMuPDF (fitz).
Called before embedding — extracts the applicant's uploaded document text.
"""
from typing import Optional
from app.core.logging import get_logger

logger = get_logger(__name__)


def extract_text_from_pdf(pdf_path: str) -> Optional[str]:
    """
    Extract all text from a PDF file.
    Returns cleaned text string, or None if extraction fails.
    """
    try:
        import fitz  # PyMuPDF

        doc = fitz.open(pdf_path)
        pages_text = []

        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text("text")
            if text.strip():
                pages_text.append(text.strip())

        doc.close()
        full_text = "\n\n".join(pages_text)

        if not full_text.strip():
            logger.warning("pdf_empty", pdf_path=pdf_path)
            return None

        # Clean up excessive whitespace
        import re
        full_text = re.sub(r'\n{3,}', '\n\n', full_text)
        full_text = re.sub(r' {2,}', ' ', full_text)

        logger.info("pdf_extracted", pdf_path=pdf_path, chars=len(full_text))
        return full_text

    except ImportError:
        logger.error("pymupdf_not_installed")
        return None
    except Exception as e:
        logger.error("pdf_extraction_failed", pdf_path=pdf_path, error=str(e))
        return None
