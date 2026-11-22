import os
from collections.abc import Callable
from pathlib import Path

SF_DATALESS = 0x40000000
DATA_DIRS = (
    Path("baselines/general"),
    Path("style/samples"),
    Path("applications"),
    Path(".state"),
)


def init_data_root(root: Path) -> list[Path]:
    created = []
    for relative in DATA_DIRS:
        path = root / relative
        if not path.is_dir():
            path.mkdir(parents=True)
            created.append(path)
    return created


def is_dataless(path: Path, stat: Callable[[Path], os.stat_result] = os.stat) -> bool:
    return bool(getattr(stat(path), "st_flags", 0) & SF_DATALESS)


def dataless_paths(root: Path, stat: Callable[[Path], os.stat_result] = os.stat) -> list[Path]:
    candidates = [root, *sorted(root.iterdir())] if root.is_dir() else []
    return [path for path in candidates if is_dataless(path, stat)]


def dataless_warning(paths: list[Path]) -> str:
    listed = "\n".join(f"  {path}" for path in paths)
    return (
        "These are cloud-only in Proton Drive. Set the data folder to 'Available offline' "
        f"in Finder, then rerun:\n{listed}"
    )
