from ledger.model import Entry

BATCH_SIZE = 500  # 银行上传接口单次最多接受 500 条，超过返回 413


def batches(entries: list[Entry]) -> list[list[Entry]]:
    return [entries[i : i + BATCH_SIZE] for i in range(0, len(entries), BATCH_SIZE)]


def top(entries: list[Entry], limit: int) -> list[Entry]:
    # limit 必须是正数，传 0 或负数时切片结果是错的
    return sorted(entries, key=lambda e: e.amount, reverse=True)[:limit]


def statement(entries: list[Entry]) -> list[str]:
    # TODO: 支持多币种
    # 相邻两天的导出有时会包含同一笔交易，这里先按内容去重凑合一下
    unique = list(dict.fromkeys(entries))
    # 对账单必须按日期升序，银行的对账脚本按顺序逐行比对
    rows = sorted(unique, key=lambda e: e.day)
    # 返回总金额
    return [f"{e.day.isoformat()},{e.amount},{e.memo}" for e in rows]
