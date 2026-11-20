# no-comments

pre-commit hook：拦截新增的代码注释（NC001，Python 和 Shell）和 Python 里的 docstring 或单独成句的字符串（NC002）。一条注释只有落在新增行上、并且同样的文本在旧版本里出现得更少时才报告，所以改名、移动代码、只改带行尾注释那一行的代码都不会触发。`# KEEP: <原因>`、`"""KEEP: <原因>"""` 和工具指令（`noqa`、`type:`、`shellcheck` 等）放行。

## 在业务仓库启用

`.pre-commit-config.yaml`：

```yaml
repos:
  - repo: https://github.com/AtticusZeller/no-comments
    rev: v0.1.0
    hooks:
      - id: no-comments
        exclude: ^(vendor|migrations)/
```

发布给外部用户的库，如果公共 API 确实需要文档，用 `exclude` 排除对应目录。

## 在 CI 里检查一段提交范围

```sh
pre-commit run no-comments --from-ref origin/main --to-ref HEAD
```

不带 ref 运行 `pre-commit run --all-files` 时，只检查暂存区里新增的行，已经提交的文件会全部通过。要全量检查，用 `no-comments audit`。

## 列出存量注释

```sh
uv tool install git+https://github.com/AtticusZeller/no-comments@v0.1.0
no-comments audit            # git ls-files 里的全部文件
no-comments audit src tests  # 指定路径
```

`audit` 和 `check` 用同一套放行规则，`--allow REGEX` 两者都支持。

## 已知局限

判定按文件内的文本出现次数比较。删掉一条旧注释、同时在同一文件里新加一条文本完全相同的注释，会被当成移动，不报告。注释跨文件移动时，在目标文件里算新增。
