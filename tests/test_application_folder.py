from datetime import date

import pytest

from resume_agent.application_folder import (
    add_timeline_event,
    create_folder,
    folder_name,
    format_id,
    next_id,
)
from resume_agent.tracker import Application, InboxRow, Tracker

DAY = date(2026, 11, 21)


def test_format_id_pads_to_five_digits():
    assert format_id(42) == "00042"
    assert format_id(123456) == "123456"


def test_next_id_starts_at_one():
    assert next_id(Tracker()) == 1


def test_next_id_counts_inbox_and_applications():
    tracker = Tracker(
        applications=[
            Application(
                id=7,
                company="Acme Health",
                role="Engineer",
            )
        ],
        inbox=[
            InboxRow(
                url="https://jobs.example.com/1",
                id=9,
            ),
            InboxRow(url="https://jobs.example.com/2"),
        ],
    )

    assert next_id(tracker) == 10


def test_folder_name():
    name = folder_name(42, "Acme Health", "Senior Software Engineer", DAY)

    assert name == "00042 Acme Health - Senior Software Engineer (2026-11-21)"


def test_folder_name_strips_unsafe_characters_and_long_parts():
    name = folder_name(1, "Globex: R&D / Labs", "Engineer " + "x" * 100, DAY)

    assert name.startswith("00001 Globex R&D Labs - Engineer xxx")
    assert "/" not in name and ":" not in name
    assert len(name) < 150


def test_folder_name_falls_back_when_empty():
    assert folder_name(1, "///", "", DAY) == "00001 Unknown - Unknown (2026-11-21)"


def test_create_folder_refuses_existing(tmp_path):
    folder = create_folder(tmp_path, "00001 Acme Health - Engineer (2026-11-21)")

    assert folder == tmp_path / "applications/00001 Acme Health - Engineer (2026-11-21)"
    with pytest.raises(FileExistsError):
        create_folder(tmp_path, folder.name)


def test_timeline_appends_dated_lines(tmp_path):
    add_timeline_event(tmp_path, DAY, "Tailored (upward, general)")
    add_timeline_event(tmp_path, date(2026, 11, 22), "Applied")

    assert (tmp_path / "timeline.md").read_text() == (
        "# Timeline\n\n- 2026-11-21 Tailored (upward, general)\n- 2026-11-22 Applied\n"
    )
