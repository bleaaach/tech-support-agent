**Seeed Studio Technical Support - How-To Guide**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear,{% endif %}

Thank you for contacting Seeed Studio. Please find the step-by-step instructions for your request below.

---

## Your Question

{{ question }}

## Step-by-Step Instructions

{{ answer }}

{% if sources %}
## Reference Documentation

{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
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
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).