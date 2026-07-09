**Seeed Studio Technical Support**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear,{% endif %}

Thank you for contacting Seeed Studio Technical Support. Please find our response below.

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
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).