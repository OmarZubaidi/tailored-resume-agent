from pathlib import Path

import pypdfium2
from ocrmac import ocrmac

RENDER_SCALE = 2


def page_lines(image) -> list[str]:
    results = ocrmac.OCR(image, recognition_level="accurate", unit="line").recognize()
    # Vision boxes are (x, y, width, height) with the origin at the bottom left.
    ordered = sorted(results, key=lambda result: (-result[2][1], result[2][0]))
    return [text for text, _, _ in ordered]


def ocr_pdf(pdf: Path) -> str:
    document = pypdfium2.PdfDocument(str(pdf))
    try:
        lines = []
        for page in document:
            image = page.render(scale=RENDER_SCALE).to_pil()
            lines.extend(page_lines(image))
        return "\n".join(lines)
    finally:
        document.close()
