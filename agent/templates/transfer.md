**Seeed Studio Customer Service**

Hi{% if customer_name %} {{ customer_name }},{% else %} Dear Customer,{% endif %}

Thank you for contacting Seeed Studio. We have received your request and will route it to the appropriate team as quickly as possible.

---

## Your Request

{{ question }}

## Next Steps

{{ answer }}

{% if sources %}
## Reference Documentation

{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

---

## Purchase & Distribution Channels

To help you reach the right team faster, please refer to the guidance below:

| If your request is about... | Please contact |
| --- | --- |
| **Order, refund, invoice, RMA, warranty** | Reply to this email — our after-sales team will follow up |
| **Pricing, quotation, bulk / B2B orders** | Our sales team at [b2b@seeedstudio.com](mailto:b2b@seeedstudio.com) |
| **Distributor / reseller partnership** | Visit [Seeed Distributors](https://www.seeedstudio.com/distributors) |
| **Already purchased from DigiKey / Mouser / Arrow** | Please contact the distributor directly for order status; we are happy to provide technical support once you have the unit in hand |
| **General technical questions** | Our Tech Support team (this ticket) |

For community discussion, the [Seeed Forum](https://forum.seeedstudio.com/) is a great place to search for answers or ask other makers.

---

We will arrange the appropriate colleague to follow up with you. Thank you for your patience.

Best Regards!
{{ agent_name | default('Seeed') }}
Seeed Technical Support Team
------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/), [Twitter/X](https://twitter.com/seeedstudio), [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) and [Facebook](https://www.facebook.com/SeeedStudio).