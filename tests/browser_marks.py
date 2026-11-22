import pytest

from resume_agent.browser import BrowserError, browser_page


def browser_launches() -> bool:
    try:
        with browser_page():
            return True
    except BrowserError:
        return False


needs_browser = pytest.mark.skipif(
    not browser_launches(),
    reason="Playwright Chromium not installed",
)
