from pathlib import Path

import pytest
import yaml
from openpyxl import Workbook
from openpyxl.styles import NamedStyle

from resume_agent.config import CONFIG_PATH_ENV
from resume_agent.tracker import TEMPLATE_STYLES

EXAMPLE_CONFIG = Path(__file__).parent.parent / "config.example.yaml"
PROTON_ACCOUNT_FOLDER = "ProtonDrive-" + "someone@example.com"
DATA_ROOT_SUFFIX = "2 Need/Career/Resume Agent Data"


@pytest.fixture(autouse=True)
def notifications(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr("resume_agent.cli.notify", sent.append)
    return sent


@pytest.fixture
def cloud_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "CloudStorage"
    (storage / PROTON_ACCOUNT_FOLDER).mkdir(parents=True)
    return storage


@pytest.fixture
def data_root(cloud_storage: Path) -> Path:
    return cloud_storage / PROTON_ACCOUNT_FOLDER / DATA_ROOT_SUFFIX


@pytest.fixture
def excel_template(tmp_path: Path) -> Path:
    workbook = Workbook()
    for name in (*TEMPLATE_STYLES, "Currency: USD"):
        if name not in workbook.named_styles:
            workbook.add_named_style(NamedStyle(name=name))
    workbook.template = True
    path = tmp_path / "Book.xltx"
    workbook.save(path)
    return path


@pytest.fixture
def config_data(cloud_storage: Path, excel_template: Path) -> dict:
    data = yaml.safe_load(EXAMPLE_CONFIG.read_text())
    data["data_root"] = str(cloud_storage / "ProtonDrive-*" / DATA_ROOT_SUFFIX)
    data["excel_template"] = str(excel_template)
    return data


@pytest.fixture
def write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    def write(data: dict) -> Path:
        path.write_text(yaml.safe_dump(data))
        return path

    return write
