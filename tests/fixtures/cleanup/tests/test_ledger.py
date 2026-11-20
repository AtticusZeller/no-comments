from datetime import date

from ledger.io import load
from ledger.model import Entry
from ledger.report import batches, statement, top

HEADER = "date,amount,memo\n"


def write(tmp_path, text, encoding="utf-8"):
    path = tmp_path / "export.csv"
    path.write_text(text, encoding=encoding)
    return path


def test_load_reads_rows(tmp_path):
    path = write(tmp_path, HEADER + "2024-01-02,1250, coffee \n")
    assert load(path) == [Entry(date(2024, 1, 2), 1250, "coffee")]


def test_load_bank_export(tmp_path):
    path = write(tmp_path, HEADER + "2024-01-02,1250,coffee\n", encoding="utf-8-sig")
    assert load(path) == [Entry(date(2024, 1, 2), 1250, "coffee")]


def test_batches_split_large_uploads():
    entries = [Entry(date(2024, 1, 1), i, "x") for i in range(1001)]
    assert [len(batch) for batch in batches(entries)] == [500, 500, 1]


def test_top_returns_largest_first():
    entries = [Entry(date(2024, 1, 1), amount, "x") for amount in (5, 30, 10)]
    assert [e.amount for e in top(entries, 2)] == [30, 10]


def test_statement_lines():
    entries = [Entry(date(2024, 1, 2), 100, "a")]
    assert statement(entries) == ["2024-01-02,100,a"]
