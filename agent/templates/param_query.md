**Seeed Studio Technical Support - Product Specifications**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear,{% endif %}

Thank you for your interest in Seeed Studio products. Please find the specifications you asked for below.

---

## Your Question

{{ question }}

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
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).