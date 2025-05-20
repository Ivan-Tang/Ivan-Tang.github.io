---
layout: single
title: "lec1"
permalink: /notes/lec1/
---

# lec1

本课程笔记：

<ul>
  {% assign pdfs = site.static_files | where_exp: "file", "file.path contains '/_notes/lec1/' and file.extname == '.pdf'" | sort: "name" %}
  {% for pdf in pdfs %}
    <li><a href="{{ pdf.path | relative_url }}">{{ pdf.name }}</a></li>
  {% endfor %}
</ul>

