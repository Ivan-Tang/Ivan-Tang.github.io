---
layout: post
title: "示例：代码、图片与 LaTeX"
date: 2026-01-23 12:30:00 +0800
author_profile: true
categories: blog
tags: [example, latex, code, image]
excerpt: "示例文章：展示如何在 post 中插入代码、图片和 LaTeX 公式。"
---

这是一个示例文章，演示如何在 Jekyll post 中插入代码、高质量图片以及 LaTeX 公式。

## 插入图片

下面是一个本地图片的示例（请把图片放到 `assets/photos/example.png` 或修改路径）：

![示意图]({{ '/assets/photos/example.png' | relative_url }})

如果图片没有显示，请把图片放到 `assets/photos/`，或者修改上面的路径为你实际的图片位置。

## 插入代码（语法高亮）

这是一个 Python 代码示例：

```python
def square(x):
    """返回 x 的平方。"""
    return x * x

if __name__ == '__main__':
    print(square(5))
```

代码块会被主题使用 Rouge 高亮（你无需额外配置）。

## 插入 LaTeX 公式（MathJax）

行内公式示例：$E=mc^2$ 或使用 \(E=mc^2\)。

显示公式示例：

\[
\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}.
\]

多行对齐示例：

\[
\begin{aligned}
a^2 + b^2 &= c^2, \\
e^{i\pi} + 1 &= 0.
\end{aligned}
\]

如果你在模板或 include 中写含 `$` 的内容，可能需要用 raw/endraw 标签包裹以避免 Liquid 解析（在正文中不要直接写出 Liquid 标签）。

---

如果你要我把这篇文章放在 `_posts/` 并本地启动预览，告诉我我就运行 `jekyll serve` 并打开本地链接。
