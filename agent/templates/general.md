{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您联系 Seeed Studio 技术支持团队。以下是我们关于您咨询问题的详细回复：

---

## 您的问题

{{ question }}

---

## 我们的回复

{{ answer }}

{% if sources or grouped_sources %}
## 参考文档
{% if grouped_sources %}
{% for group in grouped_sources %}
{% if group.items %}
### {{ group.group_name }} ({{ group.doc_type }})
{% for item in group.items %}
- [{{ item.title }}]({{ item.url }})
{% endfor %}
{% endif %}
{% endfor %}
{% else %}
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}
{% endif %}

{% if image_urls %}
## 相关图片/原理图
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## 相关资源
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

---

如有任何其他问题，欢迎直接回复此邮件。更多社区讨论，请访问 [Seeed 论坛](https://forum.seeedstudio.com/) 或加入 [Discord 社区](https://discord.gg/cpudkZmKb9)。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for contacting Seeed Studio Technical Support. Please find our response below.

---

## Your Question

{{ question }}

---

## Our Reply

{{ answer }}

{% if sources or grouped_sources %}
## Reference Documentation
{% if grouped_sources %}
{% for group in grouped_sources %}
{% if group.items %}
### {{ group.group_name }} ({{ group.doc_type }})
{% for item in group.items %}
- [{{ item.title }}]({{ item.url }})
{% endfor %}
{% endif %}
{% endfor %}
{% else %}
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}
{% endif %}

{% if image_urls %}
## Related Diagrams / Schematics
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## Related Resources
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

---

If you have any further questions, please feel free to reply to this email directly. For community discussion and peer-to-peer help, visit the [Seeed Forum](https://forum.seeedstudio.com/) or join our [Discord Community](https://discord.gg/cpudkZmKb9).

Best Regards!
Seeed Studio Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
