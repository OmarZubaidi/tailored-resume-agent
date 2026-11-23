import subprocess

import pytest

from resume_agent.notify import SCRIPT, TIMEOUT_SECONDS, TITLE, notify, problems_message


def test_notify_passes_the_message_as_an_argument():
    commands = []

    notify('Acme "Health"', lambda command, **_: commands.append(command))

    assert commands == [["osascript", "-e", SCRIPT, TITLE, 'Acme "Health"']]


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("osascript"),
        subprocess.TimeoutExpired("osascript", TIMEOUT_SECONDS),
    ],
)
def test_notify_that_cannot_run_does_nothing(error):
    def broken(command, **_):
        raise error

    notify("1 failed. See sync.log.", broken)


@pytest.mark.parametrize(
    ("failed", "flagged", "expected"),
    [
        (0, 0, None),
        (3, 0, "3 failed. See sync.log."),
        (0, 1, "1 waiting for review. See sync.log."),
        (3, 1, "3 failed, 1 waiting for review. See sync.log."),
    ],
)
def test_problems_message(failed, flagged, expected):
    assert problems_message(failed, flagged) == expected
