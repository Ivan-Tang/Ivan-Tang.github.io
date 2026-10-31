---
layout: single
title: "在 Claude Code 的终端里渲染 LaTeX：一个没写进文档的 MessageDisplay hook"
date: 2026-10-30 12:00:00 +0800
author_profile: true
categories: blog
tags: [claude-code, latex, hooks, terminal, tooling]
excerpt: "从二进制里翻出一个未公开的 hook 事件，把模型输出的 LaTeX 就地转成 Unicode 数学，以及绕不开的流式分块问题。"
---

Claude Code 的命令行界面是纯文本的。当模型输出

$$
R_{\mu\nu} - \frac{1}{2}R\,g_{\mu\nu} + \Lambda g_{\mu\nu} = \frac{8\pi G}{c^{4}} T_{\mu\nu}
$$

你在终端里看到的是一行 LaTeX 源码。网页版和桌面版会把它排版成公式，CLI 不会——这不是配置问题，是界面本身的限制。

## 两条走不通的路

第一条是"直接在终端画图片"。现代终端其实有这个能力：Ghostty、kitty、WezTerm 都支持 Kitty graphics protocol，理论上可以把公式渲染成 PNG 内联显示。但 Claude Code 的输出是它自己的 TUI 排版引擎画的，它只把文本交给终端，不会转发图片转义序列。我在二进制里搜过 `1337;File`、`sixel`、`graphics protocol`，一个都没有。

第二条是"找个消息渲染 hook"。官方文档列出的 hook 事件是 `PreToolUse`、`PostToolUse`、`UserPromptSubmit`、`Stop`、`SessionStart` 这些，没有哪个能在助手消息显示之后改写它。

所以一开始的结论是：做不到。

## 从二进制里翻出来的入口

Claude Code 是打包过的单文件二进制，`strings` 一下能看到它内部的 hook 事件枚举。在 2.1.296 里，事件列表的末尾多了几个名字，其中一个不在文档里：

```
... WorktreeCreate, WorktreeRemove, InstructionsLoaded,
    CwdChanged, FileChanged, DirectoryAdded, MessageDisplay
```

顺着 `MessageDisplay` 往下挖，schema 里带着自述文字：

- **输入**：`turn_id`、`message_id`、`index`、`final`、`delta`
- **输出**：`hookSpecificOutput.displayContent`
- **语义**：只影响屏幕显示，不改变存储的消息

有两句话特别关键：

> Fired with each batch of newly completed lines while an assistant message streams.
> Display-only: replaces the delta on screen without changing the stored message.

也就是说，它跟着流式输出走，每次给一批"刚完成的行"，而返回的 `displayContent` 会替换这一批的显示内容。再看渲染路径，替换后的文本是累加到显示缓冲区再交给 markdown 渲染器的：

```js
T.output += G          // G 就是（可能被替换过的）delta
```

所以替换不会破坏标题、列表、代码块这些格式，transcript 里存的仍然是原始 LaTeX。图片依然做不到（这里只有字符串），但**数学符号可以**。

## 把 LaTeX 换成 Unicode

注册起来很简单，`~/.claude/settings.json` 里加一段：

```json
{
  "hooks": {
    "MessageDisplay": [
      {
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/render-math.py" }
        ]
      }
    ]
  }
}
```

脚本的骨架就是一个 JSON 进、JSON 出的小程序：

```python
data = json.load(sys.stdin)
new = transform(data["delta"])
if new != data["delta"]:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "MessageDisplay",
            "displayContent": new,
        }
    }, ensure_ascii=False))
```

转换本身不复杂：一张符号表，加上对 `\frac`、`\sqrt`、上下标的递归处理。

| LaTeX | 显示 |
| --- | --- |
| `\frac{a}{b}` | a/b |
| `x^{2}` | x² |
| `\int_{0}^{1}` | ∫₀¹ |
| `\mathbb{R}` | ℝ |
| `\sum_{n=1}^{\infty}` | ∑ₙ₌₁^(∞) |
| `\oint_{S}` | ∮_S |

实际跑出来的效果是这样的：

```
E = mc²
∮_S E· dA = Q/ε₀
∑ₙ₌₁^(∞)1/n² = π²/6
```

## 真正的坑：流式分块

第一版写完，行内公式都正常，多行公式却一个都没转。这个问题花了我最久。

原因在"each batch of newly completed lines"这句话里：hook 每次拿到的不是整条消息，而是若干**完整的行**。于是一个跨行的公式块

```latex
$$
I^{2}=\left(\int_{-\infty}^{\infty}e^{-x^{2}}\,\mathrm{d}x\right)^{2}
=\iint_{\mathbb{R}^{2}}e^{-(x^{2}+y^{2})}\,\mathrm{d}x\,\mathrm{d}y
$$
```

开头的 `$$` 和结尾的 `$$` 落在两个不同的批次里，任何"匹配完整块"的正则都失效，整段原样输出。

维护跨批次的进程状态也不合适：hook 每次都是新进程，只能靠临时文件通信，一旦某次没被调用状态就错位了。最后的做法是加一条**行级兜底**：

- 整行里出现已知的 LaTeX 命令（`\int`、`\frac`、`\mathrm`……）→ 按公式处理；
- 本批次里处在 `$$` 块内 → 按公式处理；
- 单独一行的 `$$` / `\[` / `\]` → 当作分隔符丢掉。

判断依据是"**已知命令**"而不是"任意反斜杠"，这一点很重要。如果见 `\` 就处理，`C:\Users\Ivan` 这种路径会被吃掉反斜杠，`\n`、`\t` 这类转义说明也会被误伤。同理，代码块和行内代码整段跳过，`$5 和 $10` 这种金额也不会被当成公式。

## Unicode 的边界

终端字符集里没有真正的分式堆叠。`\frac{a}{b}` 只能写成 a/b，矩阵只能一行行摊开，`\sum` 的上下限只能挤在右侧。这是物理限制，不是实现偷懒。

所以日常阅读和精确排版的路径要分开：

- **看推导过程**：用 hook，公式就在对话里，零操作；
- **看公式结构**：`xelatex` 渲染成 PNG 用预览打开，或者 `pandoc --mathml` 生成自包含 HTML 丢给浏览器。这一步一定在另一个窗口，换不来。

## 一点感受

同一份 LaTeX 源码，网页上有 MathJax 排版，终端里被 hook 降级成 Unicode——下面这个公式在两种介质里会是两种样子：

$$
\sum_{n=1}^{\infty}\frac{1}{n^{2}} = \frac{\pi^{2}}{6}
$$

有意思的地方不在转换器本身（这类工具早就有），而在于：一个没有写进文档的事件，靠读二进制里的 schema 自述文字就能用起来，而且恰好被设计成"只改显示、不改数据"。这种设计留出的空间，比功能列表本身更值得注意。