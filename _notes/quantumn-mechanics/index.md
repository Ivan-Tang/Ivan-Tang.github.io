---
layout: single
title: "lec1"
permalink: /notes/quantumn-mechanics/
---

# lec1

本课程笔记：

<ul>
  {% for file in site.static_files %}
    {% if file.path contains '/_notes/quantumn-mechanics/' and file.extname == '.pdf' %}
      <li><a href="{{ file.path | relative_url }}">{{ file.name }}</a></li>
    {% endif %}
  {% endfor %}
</ul>

