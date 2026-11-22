import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from pdfminer.high_level import extract_text as pdfminer_extract
from pdfminer.psexceptions import PSException
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page

from resume_agent.browser import browser_page

LISTING_PDF = "listing.pdf"
LISTING_MD = "listing.md"
SOURCE_PREFIX = "Source: "
TITLE_PREFIX = "Title: "
PDF_SOURCE_PREFIX = "file: "
CONTENT_SELECTORS = ("main", "article", "[role=main]", "body")
MIN_CONTENT_CHARS = 200
NAVIGATION_TIMEOUT_MS = 45_000
HTTP_ERROR = 400
BLANK_LINES = re.compile(r"\n\s*\n+")


class ListingError(Exception):
    pass


@dataclass
class Listing:
    source: str
    title: str
    text: str

    def markdown(self) -> str:
        return f"{SOURCE_PREFIX}{self.source}\n{TITLE_PREFIX}{self.title}\n\n{self.text}\n"


def clean_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return BLANK_LINES.sub("\n\n", "\n".join(lines)).strip()


def page_text(page: Page) -> str:
    for selector in CONTENT_SELECTORS:
        element = page.query_selector(selector)
        if element:
            text = clean_text(element.inner_text())
            if len(text) >= MIN_CONTENT_CHARS or selector == "body":
                return text
    return ""


def one_line(text: str) -> str:
    return " ".join(text.split())


def page_title(page: Page) -> str:
    heading = page.query_selector("h1")
    if heading:
        text = one_line(heading.inner_text())
        if text:
            return text
    return one_line(page.title())


def save_listing(listing: Listing, out_dir: Path) -> Listing:
    (out_dir / LISTING_MD).write_text(listing.markdown())
    return listing


def fetch_listing(url: str, out_dir: Path) -> Listing:
    out_dir.mkdir(parents=True, exist_ok=True)
    with browser_page() as page:
        try:
            response = page.goto(url, wait_until="networkidle", timeout=NAVIGATION_TIMEOUT_MS)
        except PlaywrightError as error:
            raise ListingError(f"Could not load {url}: {error.message}") from error
        if response and response.status >= HTTP_ERROR:
            raise ListingError(f"Could not load {url}: HTTP {response.status}")
        listing = Listing(source=url, title=page_title(page), text=page_text(page))
        page.pdf(path=str(out_dir / LISTING_PDF), print_background=True)
    return save_listing(listing, out_dir)


def listing_from_pdf(pdf: Path, out_dir: Path) -> Listing:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / LISTING_PDF
    if pdf.resolve() != target.resolve():
        shutil.copyfile(pdf, target)
    try:
        text = clean_text(pdfminer_extract(str(target)))
    except PSException as error:
        raise ListingError(f"{pdf.name} is not a readable PDF: {error}") from error
    title = one_line(next((line for line in text.splitlines() if line.strip()), ""))
    listing = Listing(source=f"{PDF_SOURCE_PREFIX}{pdf.name}", title=title, text=text)
    return save_listing(listing, out_dir)


def read_listing(path: Path) -> Listing:
    header, _, text = path.read_text().partition("\n\n")
    fields = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
    return Listing(
        source=fields.get(SOURCE_PREFIX.rstrip(": "), ""),
        title=fields.get(TITLE_PREFIX.rstrip(": "), ""),
        text=text.strip(),
    )
