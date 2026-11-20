import csv
from pathlib import Path

from ledger.model import Entry


def load(path: Path) -> list[Entry]:
    """Load entries from path.

    Args:
        path: the path.

    Returns:
        list of entries.
    """
    entries = []
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            # 银行导出的文件第一个列名前面有个怪字符，读不到 date，先手动去掉
            row = {key.lstrip("﻿"): value for key, value in row.items()}
            entries.append(Entry.from_row(row))
    return entries
