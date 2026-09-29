# functest/test_risk.py
# coding: utf-8 -*-
"""
独立测试 RiskEvaluator 的评分逻辑。
跑法（项目根目录）：python functest/test_risk.py
     或在 functest/ 下：python test_risk.py
"""
import os
import sys

# functest/test_risk.py → 上两级 = 项目根
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from plugins._default.login import RiskEvaluator, LoginConfig


def main():
    print("=" * 64)
    print("  RiskEvaluator 诊断")
    print("=" * 64)

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    ev = RiskEvaluator()
    fp = ev.fingerprint

    print("\n── 系统指纹 ──")
    print(f"  计算机名:       {fp['hostname']!r}")
    print(f"  虚拟机:         {fp['vm_detected']}")

    screen = fp['screen']
    print(f"  屏幕分辨率:     {screen['width']} × {screen['height']}")
    print(f"  显示器数量:     {screen['count']}")
    print(f"  屏幕 DPI:       {screen['dpi']}")

    print(f"  系统运行时长:   {fp['uptime_minutes']} 分钟 "
          f"({fp['uptime_minutes'] / 60:.1f} 小时)")
    print(f"  系统安装天数:   {fp['install_age_days']} 天")
    print(f"  物理内存:       {fp['total_ram_gb']} GB")
    print(f"  CPU 核心数:     {fp['cpu_cores']}")
    print(f"  C 盘剩余:       {fp['system_drive_free_gb']} GB")
    print(f"  时区:           {fp['timezone']!r}")
    print(f"  语言:           {fp['language']!r}")

    print("\n── 评分 ──")
    score, detail = ev.evaluate("dummy_key")

    print(f"  总分: {score}")
    print(f"  等级: ", end="")
    for upper, name, total, need, email in LoginConfig.RISK_LEVELS:
        if score <= upper:
            print(f"{name}  (题数 {total}, 通过线 {need})")
            break

    if detail:
        print("\n  触发项：")
        for k, v in detail.items():
            print(f"    [{k}] {v}")
    else:
        print("\n  未触发任何加分项（只有基础分 10）")

    print("\n── 自动登录判定 ──")
    max_risk = LoginConfig.AUTO_LOGIN_MAX_RISK
    print(f"  阈值:       <= {max_risk}")
    print(f"  当前评分:   {score}")
    print(f"  结果:       ", end="")
    if score <= max_risk:
        print("✅ 允许 7 天自动登录")
    else:
        print("❌ 超过阈值，每次都需要完整验证")

    print("\n" + "=" * 64)


if __name__ == "__main__":
    main()