# AGENTS.md

本仓库是 pre-commit hook `no-comments`，拦截新增的注释和 docstring。行为规格以 [README 的「规则」一节](README.md#规则) 为准，本文件只写实现和开发约定，不重复规格。

## 设计

### 模块职责

| 模块 | 职责 |
| --- | --- |
| `cli.py` | 解析参数，按扩展名或 shebang 判断语言，串起 `check` 和 `audit` 的流程，决定退出码 |
| `diff.py` | 调用 git：解析新增行号和旧路径，确定旧版本 ref，读取旧版本内容 |
| `compare.py` | 按文本出现次数比较新旧版本，选出新增的注释 |
| `allow.py` | 默认放行规则和 `--allow` |
| `report.py` | 规则编号 `CODES`、输出格式、结尾提示 |
| `langs/__init__.py` | `Comment`、`Kind`、`ParseError` |
| `langs/python.py` | 用 `tokenize` 提取注释，用 `ast` 提取单独成句的字符串 |
| `langs/shell.py` | 用 tree-sitter-bash 提取 `comment` 节点 |

### 数据流

`check` 依次经过五步：

1. `collect_changes` 运行一次 diff，得到每个文件的新增行号和旧路径。
2. `base_revisions` 确定旧版本。
3. 当前文件和旧版本用同一个 `extract()` 提取注释。
4. `new_comments` 按出现次数选出新增项，再交给 `is_allowed` 过滤。
5. `report` 输出结果。

`audit` 跳过第 1、2、4 步的 diff 和比较，直接提取、过滤、输出。

### 关键决策

- 每次运行只调用一次 `git diff -M -U0`，不加路径限制。加了路径限制，git 就看不到改名的源文件，改名后的文件会被当成全新文件。
- diff 命令固定带上 `--src-prefix=a/`、`--dst-prefix=b/`、`--no-relative`、`--no-ext-diff`、`--no-textconv`、`-c core.quotepath=off`，避免受用户 git 配置影响。解析路径时要处理 C 风格引号，以及含空格的路径末尾的 TAB。`---` 和 `+++` 只在第一个 `@@` 之前当作文件头解析，因为 `-U0` 的内容行也可能以它们开头。
- 旧版本的 ref 这样取：
  - 暂存区模式用 `HEAD`；还没有任何提交时，旧版本为空。
  - 范围模式用 `git merge-base FROM TO`，和 `FROM...TO` 的 diff 基准一致。
  - 暂存区模式下如果正在 merge，取 `HEAD` 和 `MERGE_HEAD` 两边的并集，同一文本的次数取较大值，这样对方分支带来的注释不算新增。
- 比较的依据是出现次数：同一文本多出 k 次，就在新增行上按文件顺序报告前 k 条。用次数而不用集合，是为了新加一条和已有注释文本相同的注释时也能报出来。
- 比较前先规范化文本。注释取去掉 `#` 和首尾空白后的内容；docstring 用 `inspect.cleandoc` 规范缩进，挪进类里重新缩进不算新增。
- 按语法识别注释，不用正则：Python 注释用 `tokenize`，单独成句的字符串用 `ast`，Shell 用 tree-sitter。这样字符串和 heredoc 里的 `#` 不会被误判。
- 任何一步解析失败，都给出警告并跳过整个文件，不影响退出码。旧版本解析失败时，按旧版本为空处理。
- 不做自动修复，不支持配置文件；要排除路径，用 pre-commit 的 `exclude`。

## 开发

```sh
uv sync
uv run pytest
pre-commit install
```

本仓库自己的 hook 写在 `.pre-commit-config.yaml` 里，用 `repo: local` 通过 `uv run` 调用。

集成测试会调用 `pre-commit try-repo` 并执行真实的 `git commit`，需要 PATH 上有 `pre-commit`：本地缺少时这些测试跳过；在 CI 里（`CI=true`）缺少时，`test_ci_runs_integration_tests` 会失败。`try-repo` 只带上已跟踪或已暂存的文件，新建的模块要先 `git add` 再跑测试。

## 修改约束

每条约束后面注明由什么来保证：

- 本仓库不写注释和 docstring。由 `test_repository_source_has_no_comments` 和 pre-commit hook 强制。
- 运行依赖只有 `tree-sitter` 和 `tree-sitter-bash`。由 `tests/test_docs.py` 强制。
- 改放行规则时，同时改 `allow.py`、README 的放行表和对应测试。由 `tests/test_docs.py` 强制两边一致。
- 改规则编号时，同时改 `report.CODES` 和 README。由 `tests/test_docs.py` 强制。
- 新增语言时：在 `langs/` 下加一个模块实现 `extract(source: str) -> list[Comment]`，再更新 `cli.EXTENSIONS`、`.pre-commit-hooks.yaml` 里的 `types_or`、README 中支持的语言，并补测试。靠评审保证。
- 不实现 issue 以外的功能；遇到需要决定的分歧，开 issue 记录，不自行扩展范围。靠评审保证。

## 文档维护

文档和代码在同一个 PR 里更新：用户能看到的行为变了，就更新 README；设计变了，就更新本文件的「设计」一节。README 只写当前行为，没解决的问题放进 GitHub issues。

## 发布

按以下步骤发布：

1. 改 `pyproject.toml` 里的 `version`，然后运行 `uv lock`。
2. 改 README 里 `rev:` 和 `uv tool install ...@v` 中的版本号。`tests/test_docs.py` 检查这两处和 `version` 一致。
3. 合并到 `main` 后，打标签并推送：`git tag -a vX.Y.Z -m vX.Y.Z && git push origin vX.Y.Z`。
