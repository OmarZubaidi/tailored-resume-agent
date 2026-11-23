from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import Page, ViewportSize, sync_playwright

INSTALL_COMMAND = ".venv/bin/playwright install chromium"
CHROME_CHANNEL = "chrome"


class BrowserError(Exception):
    pass


@contextmanager
def browser_page(viewport: ViewportSize | None = None, chrome: bool = False) -> Iterator[Page]:
    with sync_playwright() as playwright:
        try:
            if chrome:
                browser = playwright.chromium.launch(channel=CHROME_CHANNEL, headless=False)
            else:
                browser = playwright.chromium.launch()
        except PlaywrightError as error:
            fix = "Install Google Chrome" if chrome else f"Run `{INSTALL_COMMAND}`"
            name = "Chrome" if chrome else "Chromium"
            raise BrowserError(f"Could not start {name}. {fix}. {error.message}") from error
        try:
            yield browser.new_page(viewport=viewport)
        finally:
            browser.close()
