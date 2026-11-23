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


def test_chrome_launches_visible_and_names_chrome_on_failure(monkeypatch):
    launches = []

    class FailingChromium:
        def launch(self, **options):
            launches.append(options)
            raise PlaywrightError("Chromium distribution 'chrome' is not found")

    class FakePlaywright:
        chromium = FailingChromium()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr("resume_agent.browser.sync_playwright", FakePlaywright)

    with pytest.raises(BrowserError, match="Could not start Chrome. Install Google Chrome"):
        with browser_page(chrome=True):
            pass
    assert launches == [
        {
            "channel": "chrome",
            "headless": False,
        },
    ]
