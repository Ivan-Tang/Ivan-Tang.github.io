---
layout: single
title: "Notes"
permalink: /notes/
---

# 课程笔记

欢迎访问我的课程笔记！

<ul>
  {% assign courses = site.notes | where_exp: "item", "item.path contains '/index.md'" | sort: "title" %}
  {% for course in courses %}
    {% unless course.url == page.url %}
      <li><a href="{{ course.url }}">{{ course.title }}</a></li>
    {% endunless %}
  {% endfor %}
</ul>

> 选择课程进入后可浏览各章节 PDF。
