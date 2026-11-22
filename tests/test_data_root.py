import os
from pathlib import Path

from typer.testing import CliRunner

from resume_agent.cli import app
from resume_agent.config import load_config
from resume_agent.data_root import (
    DATA_DIRS,
    SF_DATALESS,
    dataless_paths,
    init_data_root,
    is_dataless,
)


def fake_stat(dataless: set[Path]):
    def stat(path: Path) -> os.stat_result:
        flags = SF_DATALESS if path in dataless else 0
        return os.stat_result((0,) * 10, {"st_flags": flags})

    return stat


def test_init_creates_layout_in_path_with_spaces_and_at(data_root):
    created = init_data_root(data_root)

    assert created == [data_root / relative for relative in DATA_DIRS]
    assert all(path.is_dir() for path in created)


def test_init_is_idempotent(tmp_path):
    init_data_root(tmp_path)

    assert init_data_root(tmp_path) == []


def test_is_dataless_reads_flag(tmp_path):
    assert is_dataless(tmp_path, fake_stat({tmp_path}))
    assert not is_dataless(tmp_path, fake_stat(set()))


def test_dataless_paths_checks_root_and_children(tmp_path):
    workbook = tmp_path / "Job Applications.xlsx"
    workbook.write_text("")
    (tmp_path / "baselines").mkdir()

    assert dataless_paths(tmp_path, fake_stat({workbook})) == [workbook]


def test_dataless_paths_on_missing_root(tmp_path):
    assert dataless_paths(tmp_path / "missing") == []


def test_init_command(config_data, write_config):
    write_config(config_data)

    result = CliRunner().invoke(app, ["init"])

    assert result.exit_code == 0
    assert (load_config().data_root / "baselines/general").is_dir()
