from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Entry:
    """An entry in the ledger."""

    day: date
    amount: int  # 单位是分，导出文件里的金额都是整数分
    memo: str

    @classmethod
    def from_row(cls, row: dict[str, str]) -> "Entry":
        # 解析日期
        day = date.fromisoformat(row["date"])
        # 2024-03 从 float 改成 int 了，避免精度问题
        amount = int(row["amount"])
        # print(row)
        return cls(day, amount, row["memo"].strip())
