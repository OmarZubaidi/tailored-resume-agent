import pytest
from playwright.sync_api import Error as PlaywrightError

from resume_agent.browser import BrowserError, browser_page


def test_launch_failure_is_a_browser_error(monkeypatch):
    class FailingChromium:
        def launch(self, **_):
            raise PlaywrightError("Executable doesn't exist")

    class FakePlaywright:
        chromium = FailingChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("resume_agent.browser.sync_playwright", FakePlaywright)

    with pytest.raises(BrowserError, match="playwright install chromium"):
        with browser_page():
            pass
