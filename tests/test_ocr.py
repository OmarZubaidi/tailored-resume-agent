from pathlib import Path

import pytest

from resume_agent.browser import chrome_page
from resume_agent.ocr import ocr_pdf

CHROME = Path("/Applications/Google Chrome.app")
needs_chrome = pytest.mark.skipif(not CHROME.exists(), reason="Google Chrome not installed")


@needs_chrome
def test_ocr_reads_rendered_pdf_in_order(tmp_path):
    pdf = tmp_path / "listing.pdf"
    with chrome_page() as page:
        page.set_content(
            "<h1>Senior Software Engineer</h1><p>Responsibilities include building services.</p>"
        )
        page.pdf(path=str(pdf))

    text = ocr_pdf(pdf)

    assert text.splitlines()[0] == "Senior Software Engineer"
    assert "Responsibilities include building services." in text
