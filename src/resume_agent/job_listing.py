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
TITLE_WORD = re.compile(r"\w[\w+#]*")
# Headed Chrome can't print to PDF, so its page is copied into headless Chromium: the base tag
# keeps relative links working and dropping scripts stops the copy redirecting or re-blocking.
FREEZE_PAGE = """url => {
  document.querySelectorAll("script").forEach(script => script.remove());
  const base = document.createElement("base");
  base.href = url;
  document.head.prepend(base);
}"""


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


def title_words(text: str) -> str:
    return " ".join(TITLE_WORD.findall(text.lower()))


def mentions_title(title: str, text: str) -> bool:
    words = title_words(title)
    return bool(words) and f" {words} " in f" {title_words(text)} "


def page_title(page: Page, text: str) -> str:
    headings = [one_line(h.inner_text()) for h in page.query_selector_all("h1") if h.is_visible()]
    social = page.query_selector("meta[property='og:title']")
    document = one_line(page.title())
    candidates = [
        title
        for title in [
            *headings,
            one_line(social.get_attribute("content") or "") if social else "",
            document,
        ]
        if title
    ]
    fallback = headings[0] if headings else document
    return next((title for title in candidates if mentions_title(title, text)), fallback)


def save_listing(listing: Listing, out_dir: Path) -> Listing:
    (out_dir / LISTING_MD).write_text(listing.markdown())
    return listing


def save_pdf(page: Page, out_dir: Path) -> None:
    page.pdf(path=str(out_dir / LISTING_PDF), print_background=True)


def fetch_listing(url: str, out_dir: Path, chrome: bool = False) -> Listing:
    out_dir.mkdir(parents=True, exist_ok=True)
    with browser_page(chrome=chrome) as page:
        try:
            response = page.goto(url, wait_until="networkidle", timeout=NAVIGATION_TIMEOUT_MS)
            if response and response.status >= HTTP_ERROR:
                raise ListingError(f"Could not load {url}: HTTP {response.status}")
            text = page_text(page)
            listing = Listing(source=url, title=page_title(page, text), text=text)
            if not chrome:
                save_pdf(page, out_dir)
                return save_listing(listing, out_dir)
            page.evaluate(FREEZE_PAGE, page.url)
            html = page.content()
        except PlaywrightError as error:
            raise ListingError(f"Could not load {url}: {error.message}") from error
    with browser_page() as printer:
        try:
            printer.set_content(html, wait_until="load", timeout=NAVIGATION_TIMEOUT_MS)
        except PlaywrightError as error:
            raise ListingError(f"Could not print {url} to PDF: {error.message}") from error
        save_pdf(printer, out_dir)
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
