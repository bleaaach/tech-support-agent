{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您联系 Seeed Studio。以下是您所需操作的分步说明：

---

## 您的问题

{{ question }}

---

## 分步操作指南

{{ answer }}

{% if grouped_sources or sources %}
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
## 相关示意图
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## 相关下载
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

## 操作前注意事项

- 在刷机或连接外设之前，请确保设备已**完全断电**
- 请使用产品随附的**原装电源适配器**
- 如果某一步失败，请先记录终端输出（或截图）再重试，以便我们快速排查问题

如需最新教程，欢迎访问 Seeed Wiki：https://wiki.seeedstudio.com/

---

如有任何不清楚的地方或遇到意外错误，请直接回复此邮件，我们将尽快为您解答。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for contacting Seeed Studio. Please find the step-by-step instructions for your request below.

---

## Your Question

{{ question }}

---

## Step-by-Step Instructions

{{ answer }}

{% if grouped_sources or sources %}
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
## Reference Diagrams
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## Related Downloads
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

## Tips Before You Start

- Make sure the device is **fully powered off** before flashing or connecting peripherals.
- Use the **official power adapter** that shipped with your product.
- If a step fails, capture the terminal output (or a photo) before retrying — it helps us troubleshoot quickly.

For most up-to-date tutorials, visit: https://wiki.seeedstudio.com/

---

If anything is unclear or you hit an unexpected error, just reply to this email and we will help.

Best Regards!
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
