"""Copy the brand kit into site/brand/ so the static pages can load it. Results are written by
each study's runner (site/data/*.json); this script never computes a number."""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dst = ROOT / "site" / "brand"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for part in ("css", "js", "icons"):
        shutil.copytree(ROOT / "brand" / part, dst / part)
    print(f"brand -> {dst.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
