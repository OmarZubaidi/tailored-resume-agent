from pathlib import Path

import pytest
import yaml

from resume_agent.config import CONFIG_PATH_ENV

EXAMPLE_CONFIG = Path(__file__).parent.parent / "config.example.yaml"
PROTON_ACCOUNT_FOLDER = "ProtonDrive-" + "someone@example.com"
DATA_ROOT_SUFFIX = "2 Need/Career/Resume Agent Data"


@pytest.fixture
def cloud_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "CloudStorage"
    (storage / PROTON_ACCOUNT_FOLDER).mkdir(parents=True)
    return storage


@pytest.fixture
def data_root(cloud_storage: Path) -> Path:
    return cloud_storage / PROTON_ACCOUNT_FOLDER / DATA_ROOT_SUFFIX


@pytest.fixture
def config_data(cloud_storage: Path) -> dict:
    data = yaml.safe_load(EXAMPLE_CONFIG.read_text())
    data["data_root"] = str(cloud_storage / "ProtonDrive-*" / DATA_ROOT_SUFFIX)
    return data


@pytest.fixture
def write_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "config.yaml"
    monkeypatch.setenv(CONFIG_PATH_ENV, str(path))

    def write(data: dict) -> Path:
        path.write_text(yaml.safe_dump(data))
        return path

    return write
