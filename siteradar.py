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
    print("🚀 开始巡检... (触发类型: %s)" % args.trigger)
    print("=" * 60)
    
    result = run_check(trigger_type=args.trigger)
    
    print("\n" + "=" * 60)
    print("📊 巡检结果")
    print("=" * 60)
    print("运行 ID: #%s" % result['run_id'])
    print("状态: %s" % result['status'])
    print("页面数: %s" % result['total_pages'])
    print("  成功: %s" % result['completed_pages'])
    print("  失败: %s" % result['failed_pages'])
    print("耗时: %ss" % result['duration_seconds'])
    print("仪表盘: %s" % result['dashboard_path'])
    
    # 显示截图数量
    screenshot_paths = result.get('screenshot_paths', [])
    if screenshot_paths:
        print("📸 截图: %s 张（已禁用发送，改用表格展示）" % len(screenshot_paths))
    
    # 显示错误统计
    errors_by_page = result.get('errors_by_page', {})
    if errors_by_page:
        total_errors = sum(len(errs) for errs in errors_by_page.values())
        print("🔍 发现错误: %s 个（分布在 %s 个页面）" % (total_errors, len(errors_by_page)))
    
    # 显示告警
    alerts = result.get('alert_list', [])
    if alerts:
        print("\n⚠️  触发告警: %s 个:" % len(alerts))
        for i, alert in enumerate(alerts, 1):
            emoji = "🔴" if alert['severity'] == 'critical' else "🟡"
            print("  %s [%s] %s" % (emoji, alert['type'], alert['title']))
            print("     %s..." % alert['message'][:80])
    else:
        print("\n✅ 没有触发告警（部分错误已被过滤）")
    
    # 发送飞书通知
    if not args.no_notify:
        # 加载配置
        config = load_config()
        
        notifier = FeishuNotifier(
            enabled=True,
            chat_id=config.feishu.chat_id
        )
        
        # 构建 Alert 对象列表
        from src.alerts import Alert, AlertSeverity
        alert_objects = []
        page_names = {}
        
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
            if a.get('page_name') and a.get('url'):
                page_names[a['url']] = a['page_name']
        
        # 构建运行摘要
        run_summary = {
            'total_pages': result['total_pages'],
            'completed_pages': result['completed_pages'],
            'failed_pages': result['failed_pages'],
            'duration_seconds': result['duration_seconds'],
        }
        
        # 获取页面结果数据（用于表格）
        page_results = None
        try:
            from src.database import db
            page_results = db.get_page_results(result['run_id'])
            
            # 从配置中补充页面名称
            for site in config.sites:
                for page in site.pages:
                    page_names[page.url] = page.name
        except Exception as e:
            logger.warning("获取页面结果失败: %s" % e)
        
        always_send = args.trigger == "scheduled" or args.always_notify
        
        print("\n📤 发送飞书通知...")
        print("   发送截图: 禁用（改用表格展示指标）")
        
        # 使用 FeishuNotifier 发送
        if notifier._lark_cli_available:
            success = notifier.send_summary(
                alerts=alert_objects,
                run_summary=run_summary,
                always_send=always_send,
                page_results=page_results,
                page_names=page_names,
                send_screenshots=False,
                errors_by_page=errors_by_page  # 传递错误详情
            )
            
            if success:
                print("✅ 飞书通知发送成功！（表格+错误详情）")
            else:
                if always_send or alert_objects:
                    print("⚠️ 发送失败")
                else:
                    print("ℹ️ 无告警，跳过通知")
        else:
            print("❌ lark-cli 不可用，无法发送")
    
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
