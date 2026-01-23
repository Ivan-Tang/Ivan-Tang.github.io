---
layout: single
title: "量子力学"
permalink: /notes/quantumn-mechanics/
---


## 章节

{% include notes/chapter_list.html course_id="quantumn-mechanics" %}


{% comment %}
---

## （可选）自动扫描该课程目录下的 PDF

如果你不想维护 `_data/notes.yml`，也可以用下面的“自动扫描”方式；缺点是排序只能按文件名，章节顺序不一定总是你想要的。


<ul>
  {% for file in site.static_files %}
    {% if file.path contains '/files/notes/quantumn-mechanics/' and file.extname == '.pdf' %}
      <li><a href="{{ file.path | relative_url }}">{{ file.name }}</a></li>
    {% endif %}
  {% endfor %}
</ul>
{% endcomment %}

