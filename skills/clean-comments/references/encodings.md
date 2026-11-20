# 约束 → 代码

ENCODE 项从下表里选成本最低的写法。改完删掉原注释，跑全部测试。

| 注释在表达什么 | Python 的写法 | Shell 的写法 |
| --- | --- | --- |
| 变量或参数的含义、单位 | 改名，比如 `timeout_s`、`angle_rad` | 改变量名 |
| 张量形状 | jaxtyping 标注，并在测试中开启运行时检查 | 不适用 |
| 取值范围、前置条件 | `assert`，或者 `raise ValueError` | `[[ ... ]] \|\| exit 1` |
| 必须保持的行为 | 写一个测试，行为变了测试就失败 | 用 bats 或现有的测试脚本 |
| 禁止使用某个 API 或依赖方向 | ruff 的 banned-api 配置、import-linter | shellcheck 配置 |
| 一段代码在做什么 | 抽成一个命名清楚的函数 | 抽成一个函数 |
| 接口说明（docstring） | 签名和类型；框架需要的帮助文本用 `help=` 或 `description=` 显式传入 | 不适用 |

具体配置项以各工具当前版本的文档为准，改配置前先查文档。

## 选择

- 改名只改本次范围内的符号。公共接口（被范围外代码或外部用户调用的名字）改名属于接口变更，不在这一步做，记为「未落地」。
- 前置条件：调用方传入的是外部输入时用 `raise ValueError`；只有内部调用、违反即是程序错误时用 `assert`。
- 张量形状的写法见 no-comments README 的「ML 代码里的张量形状」一节。
- 测试名要说明它锁住的行为，比如 `test_statement_rows_are_sorted_by_date`。
