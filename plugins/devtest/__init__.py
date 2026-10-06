"""
开发者测试脚本集合。

放在 plugins/ 下方便组织，但 plugin_manager 会跳过这个目录，
不把这里的脚本当插件加载。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class DevScript:
    id: str         # 唯一标识
    name: str       # 界面显示名
    desc: str       # 一句话描述
    module: str     # 对应的 .py 文件名（不含扩展名）


SCRIPTS = [
    DevScript(
        "ipv4", "IPv4 回退诊断",
        "对比默认 / 强制 IPv4 / Session 复用下的连接耗时",
        "check_ipv4",
    ),
    DevScript(
        "web_timeout", "网络超时诊断",
        "分阶段计时：DNS / TCP / SSL / requests / Session",
        "check_web_requests_timeout",
    ),
    DevScript(
        "webproxy", "代理环境检查",
        "打印 HTTP_PROXY / HTTPS_PROXY / requests 实际使用的代理",
        "check_webproxy",
    ),
    DevScript(
        "topic_requests", "图片请求测试",
        "向 p5.toutiaoimg.com 发一次请求并计时",
        "check_topic_requests",
    ),
    DevScript(
        "usb", "USB 设备探测",
        "列出可移动磁盘及其卷序列号 / 卷标 / USB ID",
        "check_usb",
    ),
    DevScript(
        "risk", "风控评分诊断",
        "打印系统指纹并计算 RiskEvaluator 评分",
        "check_risk",
    ),
    DevScript(
        "compare_text", "MD / HTML 格式对比",
        "采样多个帖子，对比 Markdown 和 HTML 的差异（耗时较久）",
        "check_compare_text",
    ),
]