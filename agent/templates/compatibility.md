**Seeed Studio Technical Support - Compatibility**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear,{% endif %}

Thank you for contacting Seeed Studio. Below is our response regarding the compatibility question you raised.

---

## Your Question

{{ question }}

## Our Reply

{{ answer }}

{% if sources %}
## Reference Documentation

{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
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
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).