{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您对 Seeed Studio 产品的关注。以下是我们关于产品规格的详细回复：

---

## 您的问题

{{ question }}

---

## 产品规格

{{ answer }}

{% if sources %}
## 参考文档
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

{% if image_urls %}
## 机械图纸/尺寸图
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## 数据手册与下载
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

## 其他资源

产品资料均可在 Wiki 页面的 **Resources** 区域找到。如需以下资料，直接回复邮件告知，我们即可发送下载链接：

- **数据手册**（PDF）
- **机械图纸** / 3D 模型（STP / STEP / DXF / STL / OBJ）
- **原理图**（如有）
- **认证报告**（CE / FCC / RoHS）

您也可以访问 Seeed Wiki 浏览所有产品文档：https://wiki.seeedstudio.com/

---

如有任何其他问题，欢迎直接回复此邮件。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for your interest in Seeed Studio products. Please find the specifications you asked for below.

---

## Your Question

{{ question }}

---

## Specifications

{{ answer }}

{% if sources %}
## Reference Documentation
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

{% if image_urls %}
## Mechanical Drawings / Dimensions
{% for url in image_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

{% if resource_urls %}
## Datasheets & Downloads
{% for url in resource_urls[:3] %}
- {{ url }}
{% endfor %}
{% endif %}

## Additional Resources

Most product assets are available on the product wiki page under the **Resources** section. If you need any of the following, just reply and let us know — we will send the direct link:

- **Datasheet** (PDF)
- **Mechanical drawing** / STEP file / 3D model (STP / STEP / DXF / STL / OBJ)
- **Schematic** (when applicable)
- **Certification reports** (CE / FCC / RoHS)

You can also browse all product documentation at: https://wiki.seeedstudio.com/

---

Best Regards!
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
