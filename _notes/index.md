---
layout: single
title: "Notes"
permalink: /notes/
---

# 课程笔记

欢迎访问我的课程笔记！

## 课程列表

{% assign notes_data = site.data.notes %}
{% if notes_data and notes_data.courses %}
  {% include notes/course_list.html %}
{% else %}
  {% comment %}
    兜底：如果你还没维护 `_data/notes.yml`，依然可以通过课程目录里的 `index.md` 自动聚合。
  {% endcomment %}

  <ul>
    {% assign courses = site.notes | where_exp: "item", "item.path contains '/index.md'" | sort: "title" %}
    {% for course in courses %}
      {% unless course.url == page.url %}
        <li><a href="{{ course.url }}">{{ course.title }}</a></li>
      {% endunless %}
    {% endfor %}
  </ul>
{% endif %}

> 进入课程后，你会看到“章节 → PDF”的目录结构。
