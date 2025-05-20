---
layout: single
title: "Notes"
permalink: /notes/
---

# 课程笔记

欢迎访问我的课程笔记！

{% assign notes_collections = site.notes | sort: 'title' %}
<ul>
  {% for note in notes_collections %}
    <li><a href="{{ note.url }}">{{ note.title }}</a></li>
  {% endfor %}
</ul>

> 选择课程进入后可浏览各章节 PDF。
