**Seeed Studio Technical Support - Troubleshooting**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear,{% endif %}

Thank you for contacting Seeed Studio Technical Support. To help us resolve this issue as quickly as possible, please review the suggestions below.

---

## Your Question

{{ question }}

## Initial Response

{{ answer }}

## Suggested Troubleshooting Steps

Please work through the steps below in order, and let us know the result of each:

1. **Power and physical connections** — Confirm the official power adapter is used, fully seated, and that the status LEDs behave as expected.
2. **Network and cables** — Try a different cable / port, and confirm the link LED is on.
3. **Firmware / software** — Verify the JetPack version matches our [wiki guide](https://wiki.seeedstudio.com/) for your product, and re-flash if needed.
4. **Reproduction** — Try to reproduce the issue after each step and note any new error messages, screenshots, or logs (use `jtop` for thermal / power diagnostics).

## Historical Reference Patterns

When troubleshooting Seeed Jetson / reComputer issues, our agents typically follow this pattern (inspired by successful past tickets):

> **Pattern 1 — Confirm device state first**
> "Thank you for contacting Seeed Studio. To better understand the issue, could you please help clarify the following?
> 1. When you power on the device, is the system already configured, or is this the initial setup?
> 2. Could you share a screenshot or photo showing the current behavior?
> We look forward to your reply."

> **Pattern 2 — Try wiki-guided steps before hardware RMA**
> "Regarding your issue, we tested the official image from our Wiki and could not reproduce the problem. Please power-cycle the device (disconnect power), re-enter Recovery Mode, and try flashing again. If the issue persists, the device may need inspection — we can arrange RMA."

> **Pattern 3 — Escalate with full diagnostic bundle**
> "To help resolve your issue faster, please confirm: (1) device SKU + JetPack version (`cat /etc/nv_tegra_release`); (2) a photo or video of the issue; (3) which steps you have already tried; (4) purchase channel and order number (for warranty check)."

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

## Information We Need From You

To help us investigate further, please share the following:

1. Product model (SKU if available) and the JetPack version installed (`cat /etc/nv_tegra_release`).
2. A photo or short video showing the current behavior and any on-screen messages.
3. Which troubleshooting steps you have already tried.
4. Purchase channel and order number (so we can check warranty status).

---

If the issue cannot be resolved through the steps above and the device is within warranty, we can assist further with the RMA / replacement process. For community help, visit the [Seeed Forum](https://forum.seeedstudio.com/).

Best Regards!
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).