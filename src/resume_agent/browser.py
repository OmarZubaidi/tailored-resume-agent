from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, ViewportSize, sync_playwright


class BrowserError(Exception):
    pass


@contextmanager
def chrome_page(viewport: ViewportSize | None = None) -> Iterator[Page]:
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel="chrome")
        except PlaywrightError as error:
            raise BrowserError(f"Could not start Google Chrome: {error.message}") from error
        try:
            yield browser.new_page(viewport=viewport)
        finally:
            browser.close()
