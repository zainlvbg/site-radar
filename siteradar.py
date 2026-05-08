#!/usr/bin/env python3
"""
SiteRadar - 网站智能巡检系统
命令行入口
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from datetime import datetime

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.checker import run_check, run_check_async
from src.config import load_config
from src.database import db
from src.dashboard import DashboardGenerator
from src.feishu_notifier import FeishuNotifier


def send_feishu_message(message: str) -> bool:
    """
    发送消息到飞书
    
    注意：这个函数在 Hermes 环境中运行时，可以使用 send_message 工具
    但在独立运行时，我们只返回消息内容
    """
    try:
        # 尝试使用 Hermes 的 send_message 工具
        # 这里通过 print 输出消息，供 Hermes cron job 捕获
        print(f"\n[FEISHU_MESSAGE]\n{message}\n[FEISHU_MESSAGE_END]\n")
        return True
    except Exception as e:
        print(f"发送飞书消息失败: {e}")
        return False


def cmd_run(args):
    """执行巡检"""
    print(f"🚀 开始巡检... (触发类型: {args.trigger})")
    print("=" * 60)
    
    result = run_check(trigger_type=args.trigger)
    
    print("\n" + "=" * 60)
    print("📊 巡检结果")
    print("=" * 60)
    print(f"运行 ID: #{result['run_id']}")
    print(f"状态: {result['status']}")
    print(f"页面数: {result['total_pages']}")
    print(f"  成功: {result['completed_pages']}")
    print(f"  失败: {result['failed_pages']}")
    print(f"耗时: {result['duration_seconds']}s")
    print(f"仪表盘: {result['dashboard_path']}")
    
    # 显示截图数量
    screenshot_paths = result.get('screenshot_paths', [])
    if screenshot_paths:
        print(f"📸 截图: {len(screenshot_paths)} 张")
    
    # 显示告警
    alerts = result.get('alert_list', [])
    if alerts:
        print(f"\n⚠️  发现 {len(alerts)} 个告警:")
        for i, alert in enumerate(alerts, 1):
            emoji = "🔴" if alert['severity'] == 'critical' else "🟡"
            print(f"  {emoji} [{alert['type']}] {alert['title']}")
            print(f"     {alert['message']}")
            print(f"     URL: {alert['url']}")
    else:
        print("\n✅ 没有发现告警")
    
    # 发送飞书通知（如果有告警或强制发送）
    if not args.no_notify:
        # 加载配置获取飞书设置
        config = load_config()
        
        notifier = FeishuNotifier(
            enabled=True,
            chat_id=config.feishu.chat_id
        )
        
        # 构建 Alert 对象列表
        from src.alerts import Alert, AlertSeverity
        alert_objects = []
        for a in alerts:
            severity = AlertSeverity.CRITICAL if a['severity'] == 'critical' else AlertSeverity.WARNING
            alert_objects.append(Alert(
                alert_type=a['type'],
                severity=severity,
                title=a['title'],
                message=a['message'],
                url=a['url'],
                page_name=a.get('page_name', '')
            ))
        
        # 构建运行摘要
        run_summary = {
            'total_pages': result['total_pages'],
            'completed_pages': result['completed_pages'],
            'failed_pages': result['failed_pages'],
            'duration_seconds': result['duration_seconds'],
        }
        
        # 生成消息 - 如果是定时触发，总是发送报告；如果是手动，有告警才发送
        always_send = args.trigger == "scheduled" or args.always_notify
        
        # 确定要发送的截图
        screenshots_to_send = []
        if config.feishu.send_screenshots and screenshot_paths:
            # 如果有告警，优先发送有告警页面的截图
            # 否则发送最新的几张截图
            max_screenshots = config.feishu.max_screenshots
            screenshots_to_send = screenshot_paths[-max_screenshots:]  # 取最新的几张
        
        print(f"\n📤 发送飞书通知...")
        print(f"   截图数量: {len(screenshots_to_send)}/{len(screenshot_paths)}")
        
        # 使用 FeishuNotifier 发送
        if notifier._lark_cli_available:
            # lark-cli 可用，直接发送
            success = notifier.send_summary(
                alerts=alert_objects,
                run_summary=run_summary,
                always_send=always_send,
                screenshot_paths=screenshots_to_send
            )
            
            if success:
                print("✅ 飞书通知发送成功！")
            else:
                print("⚠️  无告警，跳过通知")
        else:
            # lark-cli 不可用，返回消息供 send_message 工具发送
            message = notifier.format_summary_message(alert_objects, run_summary)
            
            if always_send or alerts:
                send_feishu_message(message)
                print("✅ 飞书通知已准备好（通过 Hermes send_message）")
            else:
                print("ℹ️  无告警，跳过通知")
    
    return 0


def cmd_dashboard(args):
    """生成仪表盘"""
    print("📊 生成仪表盘...")
    
    generator = DashboardGenerator()
    output_path = generator.generate()
    
    print(f"✅ 仪表盘已生成: {output_path}")
    print(f"\n💡 提示: 用浏览器打开此文件查看完整报告")
    
    return 0


def cmd_config(args):
    """查看配置"""
    config = load_config()
    
    print("📋 当前配置")
    print("=" * 60)
    print(f"调度: {config.schedule}")
    print(f"并发数: {config.max_concurrent}")
    print(f"页面超时: {config.page_timeout}ms")
    print(f"告警渠道: {', '.join(config.alert_channels)}")
    
    print(f"\n站点配置 ({len(config.sites)} 个站点):")
    for site in config.sites:
        status = "✅" if site.is_active else "⏸️"
        print(f"\n  {status} {site.name} ({site.base_url})")
        print(f"     页面数: {len(site.pages)}")
        
        for page in site.pages:
            page_status = "✅" if page.is_active else "⏸️"
            checks = []
            if page.check_performance: checks.append("性能")
            if page.check_errors: checks.append("错误")
            if page.capture_screenshot: checks.append("截图")
            print(f"       {page_status} {page.name}")
            print(f"          URL: {page.url}")
            print(f"          检查项: {', '.join(checks)}")
    
    return 0


def cmd_list(args):
    """列出运行历史"""
    print("📋 运行历史")
    print("=" * 60)
    
    runs = db.get_latest_runs(limit=args.limit)
    
    if not runs:
        print("暂无运行记录")
        return 0
    
    print(f"{'ID':<6} {'状态':<12} {'触发类型':<12} {'页面数':<8} {'开始时间'}")
    print("-" * 80)
    
    for run in runs:
        run_id = run['id']
        status = run['status']
        trigger = run['trigger_type']
        pages = f"{run['completed_pages']}/{run['total_pages']}"
        started_at = run['started_at']
        
        # 格式化状态
        status_emoji = "🏃" if status == "running" else "✅" if status == "completed" else "❌"
        
        print(f"{run_id:<6} {status_emoji} {status:<10} {trigger:<12} {pages:<8} {started_at}")
    
    return 0


def cmd_show(args):
    """显示运行详情"""
    run_id = args.run_id
    
    print(f"📋 运行详情 #{run_id}")
    print("=" * 60)
    
    run = db.get_run(run_id)
    if not run:
        print(f"❌ 找不到运行 #{run_id}")
        return 1
    
    print(f"UUID: {run['run_uuid']}")
    print(f"状态: {run['status']}")
    print(f"触发类型: {run['trigger_type']}")
    print(f"页面数: {run['completed_pages']}/{run['total_pages']}")
    print(f"开始时间: {run['started_at']}")
    print(f"完成时间: {run.get('completed_at', '-')}")
    
    # 页面结果
    results = db.get_page_results(run_id)
    if results:
        print(f"\n📄 页面结果 ({len(results)} 个):")
        for r in results:
            status = "✅" if r['status'] == 'success' else "❌"
            score = f"得分: {r['lh_performance_score']}" if r.get('lh_performance_score') else ""
            print(f"  {status} {r['url'][:60]}... {score}")
    
    # 错误
    errors = db.get_run_errors(run_id)
    if errors:
        print(f"\n❌ 错误 ({len(errors)} 个):")
        for e in errors:
            level = "🔴" if e['level'] == 'error' else "🟡"
            print(f"  {level} [{e['error_type']}] {e['message'][:80]}...")
    
    return 0


def cmd_test_page(args):
    """测试单个页面（不保存到数据库）"""
    print(f"🧪 测试页面: {args.url}")
    print("=" * 60)
    
    from src.browser import inspect_url
    
    async def test():
        result = await inspect_url(
            url=args.url,
            capture_screenshot=True,
            screenshot_name="test"
        )
        
        print(f"\n📊 测试结果:")
        print(f"  状态: {result.status}")
        print(f"  HTTP 状态码: {result.http_status}")
        print(f"  加载时间: {result.load_time}ms")
        print(f"  截图: {result.screenshot_path}")
        
        print(f"\n  📋 Console 错误: {len(result.console_errors)}")
        for err in result.console_errors[:5]:
            print(f"     ❌ {err.text}")
        
        print(f"\n  📋 Console 警告: {len(result.console_warnings)}")
        for warn in result.console_warnings[:5]:
            print(f"     ⚠️  {warn.text}")
        
        print(f"\n  📋 网络错误: {len(result.network_errors)}")
        for net_err in result.network_errors[:5]:
            print(f"     🌐 HTTP {net_err.status}: {net_err.url}")
        
        print(f"\n  📋 页面异常: {len(result.page_exceptions)}")
        for exc in result.page_exceptions[:5]:
            print(f"     💥 {exc.message}")
        
        return result
    
    result = asyncio.run(test())
    return 0


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="SiteRadar - 网站智能巡检系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  siteradar run                    执行一次巡检
  siteradar run --trigger scheduled  标记为定时触发
  siteradar dashboard              生成仪表盘
  siteradar config                 查看当前配置
  siteradar list                   列出运行历史
  siteradar show 1                 查看运行 #1 的详情
  siteradar test https://example.com  测试单个页面
        """
    )
    
    subparsers = parser.add_subparsers(title="命令", dest="command")
    
    # run 命令
    run_parser = subparsers.add_parser("run", help="执行巡检")
    run_parser.add_argument("--trigger", default="manual", choices=["manual", "scheduled"],
                           help="触发类型 (默认: manual)")
    run_parser.add_argument("--no-notify", action="store_true",
                           help="不发送飞书通知")
    run_parser.add_argument("--always-notify", action="store_true",
                           help="总是发送通知（即使没有告警）")
    run_parser.set_defaults(func=cmd_run)
    
    # dashboard 命令
    dash_parser = subparsers.add_parser("dashboard", help="生成仪表盘")
    dash_parser.set_defaults(func=cmd_dashboard)
    
    # config 命令
    config_parser = subparsers.add_parser("config", help="查看配置")
    config_parser.set_defaults(func=cmd_config)
    
    # list 命令
    list_parser = subparsers.add_parser("list", help="列出运行历史")
    list_parser.add_argument("-n", "--limit", type=int, default=10, help="显示数量 (默认: 10)")
    list_parser.set_defaults(func=cmd_list)
    
    # show 命令
    show_parser = subparsers.add_parser("show", help="显示运行详情")
    show_parser.add_argument("run_id", type=int, help="运行 ID")
    show_parser.set_defaults(func=cmd_show)
    
    # test 命令
    test_parser = subparsers.add_parser("test", help="测试单个页面")
    test_parser.add_argument("url", help="页面 URL")
    test_parser.set_defaults(func=cmd_test_page)
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
