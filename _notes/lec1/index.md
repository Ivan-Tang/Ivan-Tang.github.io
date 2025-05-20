---
layout: single
title: "课程名示例"
permalink: /notes/lec1/
---

# 课程名示例

本课程笔记：

<ul>
{% assign pdfs = site.static_files | where_exp: "file", "file.path contains '/_notes/lec1/' and file.extname == '.pdf'" | sort: 'name' %}
  {% for pdf in pdfs %}
    <li><a href="{{ pdf.path }}">{{ pdf.name }}</a></li>
  {% endfor %}
</ul>

> 请将本文件复制到每门课程目录下，并修改 title。
