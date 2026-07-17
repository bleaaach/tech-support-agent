{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您联系 Seeed Studio。我们已收到您的请求，将尽快为您转接至相应团队处理。

---

## 您的问题

{{ question }}

---

## 后续处理

{{ answer }}

{% if sources %}
## 参考文档
{% for source in sources %}
- [{{ source.title }}]({{ source.url }})
{% endfor %}
{% endif %}

---

## 快速对接指引

为节省您的宝贵时间，以下信息可帮助您更快找到对应的团队：

| 如果您的需求是... | 请联系 |
|---|---|
| **订单、退款、发票、RMA、保修** | 直接回复此邮件，售后团队将跟进处理 |
| **价格、报价、批量/B2B采购** | 发邮件至 [b2b@seeedstudio.com](mailto:b2b@seeedstudio.com)，我们的销售团队将为您服务 |
| **经销商/代理商合作** | 访问 [Seeed 经销商页面](https://www.seeedstudio.com/distributors) |
| **已在 DigiKey / Mouser / Arrow 购买** | 请直接联系分销商查询订单状态；收到设备后我们很乐意提供技术支持 |
| **一般技术问题** | 我们的技术支持团队（当前工单）随时为您服务 |

如需社区讨论和问题解答，也欢迎访问 [Seeed 论坛](https://forum.seeedstudio.com/)。

---

感谢您的耐心等待，我们将尽快安排相应同事跟进处理。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for contacting Seeed Studio. We have received your request and will route it to the appropriate team as quickly as possible.

---

## Your Request

{{ question }}

---

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
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
