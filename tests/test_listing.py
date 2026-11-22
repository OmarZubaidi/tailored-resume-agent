import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from browser_marks import needs_browser

from resume_agent.job_listing import (
    LISTING_MD,
    LISTING_PDF,
    Listing,
    ListingError,
    clean_text,
    fetch_listing,
    listing_from_pdf,
    read_listing,
)

REQUIREMENTS = " ".join(f"Experience with system number {n}." for n in range(30))
PAGE = f"""<!doctype html>
<html><head><title>Careers | Acme</title></head>
<body>
<nav>Home Jobs About</nav>
<main>
  <h1>Senior Software Engineer</h1>
  <h2>Responsibilities</h2>
  <p>Build services.</p>
  <h2>Requirements</h2>
  <p>{REQUIREMENTS}</p>
</main>
<footer>Copyright</footer>
</body></html>
"""


def test_clean_text_collapses_blank_lines():
    assert clean_text("  a  \n\n\n   \n b \n") == "a\n\nb"


def test_listing_markdown_round_trips(tmp_path):
    listing = Listing(source="https://example.com/job", title="Engineer", text="Line one\n\nTwo")
    (tmp_path / LISTING_MD).write_text(listing.markdown())

    assert read_listing(tmp_path / LISTING_MD) == listing


def test_non_pdf_is_a_listing_error(tmp_path):
    fake = tmp_path / "fake.pdf"
    fake.write_text("not a pdf")

    with pytest.raises(ListingError, match="fake.pdf is not a readable PDF"):
        listing_from_pdf(fake, tmp_path / "out")


@pytest.fixture
def not_found_url():
    class NotFound(BaseHTTPRequestHandler):
        def do_GET(self):
            body = f"<main><h1>Not found</h1><p>{REQUIREMENTS}</p></main>".encode()
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = HTTPServer(("127.0.0.1", 0), NotFound)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}/job"
    server.shutdown()


@needs_browser
def test_http_error_page_is_rejected(tmp_path, not_found_url):
    with pytest.raises(ListingError, match="HTTP 404"):
        fetch_listing(not_found_url, tmp_path)


@needs_browser
def test_multi_line_heading_becomes_one_line_title(tmp_path):
    page = tmp_path / "job.html"
    heading = "<h1>Senior Software Engineer</h1>"
    page.write_text(PAGE.replace(heading, "<h1>Senior<br><br>Engineer</h1>"))

    listing = fetch_listing(page.as_uri(), tmp_path / "out")

    assert listing.title == "Senior Engineer"
    assert read_listing(tmp_path / "out" / LISTING_MD).title == "Senior Engineer"


@needs_browser
def test_fetch_listing_saves_pdf_and_main_text(tmp_path):
    page = tmp_path / "job.html"
    page.write_text(PAGE)
    out = tmp_path / "out"

    listing = fetch_listing(page.as_uri(), out)

    assert listing.title == "Senior Software Engineer"
    assert "Responsibilities" in listing.text
    assert "Home Jobs About" not in listing.text
    assert (out / LISTING_PDF).read_bytes().startswith(b"%PDF")
    assert read_listing(out / LISTING_MD) == listing


@needs_browser
def test_fetch_listing_unreachable_url(tmp_path):
    with pytest.raises(ListingError, match="Could not load"):
        fetch_listing("http://localhost:9/nothing", tmp_path)


@needs_browser
def test_listing_from_supplied_pdf(tmp_path):
    page = tmp_path / "job.html"
    page.write_text(PAGE)
    fetch_listing(page.as_uri(), tmp_path / "fetched")
    printed = tmp_path / "printed.pdf"
    printed.write_bytes((tmp_path / "fetched" / LISTING_PDF).read_bytes())

    listing = listing_from_pdf(printed, tmp_path / "out")

    assert listing.source == "file: printed.pdf"
    assert "Requirements" in listing.text
    assert (tmp_path / "out" / LISTING_PDF).exists()
