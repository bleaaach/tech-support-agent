{% if lang == 'zh' %}您好{% if customer_name %} {{ customer_name }}{% endif %}，

感谢您联系 Seeed Studio 技术支持团队。我们已收到您的问题，以下是我们的详细回复：

{{ answer }}

如需进一步帮助，请随时回复此邮件。如需社区讨论和技术支持，欢迎访问 [Seeed 论坛](https://forum.seeedstudio.com/) 或加入我们的 [Discord 社区](https://discord.gg/cpudkZmKb9)。

此致
Seeed Studio 技术支持团队
------------------------------------------------------------------
我们的工作时间为：周一至周五 9:00 AM - 6:00 PM GMT+8
关注我们：[LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% else %}Hi{% if customer_name %} {{ customer_name }}{% endif %},

Thank you for contacting Seeed Studio Technical Support. Please find our detailed response below.

{{ answer }}

If you have any further questions, please feel free to reply to this email directly. For community discussion and peer-to-peer help, visit the [Seeed Forum](https://forum.seeedstudio.com/) or join our [Discord Community](https://discord.gg/cpudkZmKb9).

Best regards!
Seeed Studio Technical Support Team
------------------------------------------------------------------
Our working hours are 9:00 AM - 6:00 PM GMT+8, Monday - Friday.
Follow us on [LinkedIn](https://www.linkedin.com/company/seeed-studio/) | [Twitter/X](https://twitter.com/seeedstudio) | [YouTube](https://www.youtube.com/c/SeeedStudioOfficial) | [Facebook](https://www.facebook.com/SeeedStudio){% endif %}
