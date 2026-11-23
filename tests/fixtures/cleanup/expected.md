# 预期判定

clean-comments 在这个样例项目上的预期结果，范围是整个项目。改了 `reviewer.md`、`investigate.md`、`encodings.md` 或 `redesign.md` 之后，把本目录除 `expected.md` 以外的文件复制到一个新的 git 仓库，无人值守跑一遍 skill，并授权第二次提交改写代码；然后和下表对比。外部约束的证据在 `docs/bank-api.md`。

| 位置 | 判定 | 预期处理 |
| --- | --- | --- |
| ledger/__init__.py:1:1 | DELETE | 模块 docstring 复述包名 |
| ledger/model.py:7:5 | DELETE | docstring 复述类名 |
| ledger/model.py:10:18 | ENCODE | `amount` 改名为 `amount_cents`，依据是 `docs/bank-api.md` 里的金额单位 |
| ledger/model.py:15:9 | DELETE | 复述代码 |
| ledger/model.py:17:9 | DELETE | 改动历史 |
| ledger/model.py:19:9 | DELETE | 被注释掉的代码 |
| ledger/io.py:8:5 | DELETE | docstring 复述签名 |
| ledger/io.py:19:13 | WORKAROUND | 手动去掉 BOM；根因是用 `utf-8` 而不是 `utf-8-sig` 打开带 BOM 的导出文件。去掉这行 hack，`test_load_bank_export` 会失败。满足范围内修复的条件，但无人值守时只写锁定测试，不改代码 |
| ledger/report.py:3:19 | KEEP | 银行上传接口的条数上限，证据是 `docs/bank-api.md` |
| ledger/report.py:3:50 | DELETE | 复述赋值 |
| ledger/report.py:11:5 | ENCODE | 负数 `limit` 会让切片丢掉末尾的元素（`0` 返回空列表，不算错）；`top` 只有内部调用，写成 `assert limit >= 0`，加测试 |
| ledger/report.py:12:5 | DELETE | 约束成立，但 `test_top_returns_largest_first` 已经锁住了排序方向 |
| ledger/report.py:17:5 | DELETE | 没有负责人、也没有链接的 TODO |
| ledger/report.py:18:5 | WORKAROUND | 按内容去重会把真正相同的两笔交易合并；根因是没有交易流水号。修复要在网银后台开启 `txn_id` 列，并给 `Entry` 加字段，超出范围，写草图 |
| ledger/report.py:20:5 | ENCODE | 写测试锁定对账单按日期升序 |
| ledger/report.py:22:5 | DELETE | 和代码对不上，函数返回的是对账单行 |
| scripts/check.sh:3:1 | DELETE | 复述代码 |

预期得到三次提交：

1. 只动注释：删掉 11 条 DELETE，把 `ledger/report.py:3:19` 改写成 `# KEEP: ...（docs/bank-api.md）`，写在 `BATCH_SIZE` 上一行。`no-comments verify-strip --base HEAD` 通过，并列出被删掉的 3 个 docstring：`__init__.py` 的模块 docstring、`Entry`、`load`。
2. 改写成代码：3 条 ENCODE。
3. 重新设计：给两条 WORKAROUND 各写一个锁定测试（已有的 `test_load_bank_export` 改个能说明锁住什么的名字也算），去掉 hack 后这两个测试都失败；删掉注释，两份草图写进报告。

最后 `no-comments audit` 输出为空，代码里只剩 `report.py:3` 一条 `KEEP:` 注释。
