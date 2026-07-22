{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您联系 Seeed Studio。以下是我们关于您咨询的兼容性问题的详细回复：

---

## 您的问题

{{ question }}

---

## 我们的回复

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
## 相关接口图/接线说明
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

## 兼容性补充说明

如需确认的具体配件不在上述列表中，请回复时提供以下信息，我们将为您核实官方兼容性列表：

1. 具体的模块/外设型号
2. 当前运行的 JetPack / L4T 版本（运行 `cat /etc/nv_tegra_release`）
3. 相关错误日志或 `dmesg` 输出

---

如有任何其他问题，欢迎直接回复此邮件。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for contacting Seeed Studio. Below is our response regarding the compatibility question you raised.

---

## Your Question

{{ question }}

---

## Our Reply

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
## Related Diagrams / Interface Notes
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

## Compatibility Notes

If the exact item you need is not listed, please reply with:
1. The exact module / peripheral model number
2. The JetPack / L4T version you are running (`cat /etc/nv_tegra_release`)
3. Any error logs or `dmesg` output

We will then check the official compatibility matrix and follow up.

---

Best Regards!
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
