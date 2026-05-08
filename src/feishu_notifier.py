"""
飞书告警模块 - 集成 lark-cli 发送消息
支持表格形式展示指标
"""

import logging
import os
import subprocess
import shutil
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from src.alerts import Alert, AlertSeverity

logger = logging.getLogger("site-radar.feishu")


class FeishuNotifier:
    """飞书通知器"""
    
    def __init__(
        self, 
        enabled=True,
        chat_id=None,
        lark_cli_path=None
    ):
        self.enabled = enabled
        self.chat_id = chat_id
        
        # 查找 lark-cli 路径
        if lark_cli_path:
            self.lark_cli = lark_cli_path
        else:
            self.lark_cli = self._find_lark_cli()
        
        # 验证 lark-cli 是否可用
        if self.lark_cli:
            self._lark_cli_available = self._check_lark_cli()
        else:
            self._lark_cli_available = False
        
        logger.info("飞书通知器: enabled=%s, chat_id=%s, lark_available=%s",
                    enabled, chat_id, self._lark_cli_available)
    
    def _find_lark_cli(self):
        """查找 lark-cli 可执行文件"""
        if shutil.which("lark-cli"):
            return "lark-cli"
        
        possible_paths = [
            "/Users/frontend/.local/bin/lark-cli",
            "/opt/homebrew/lib/node_modules/@larksuite/cli/scripts/run.js",
        ]
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        return None
    
    def _check_lark_cli(self):
        """检查 lark-cli 是否可用"""
        try:
            result = subprocess.run(
                [self.lark_cli, "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _format_ms(self, ms):
        """格式化毫秒数"""
        if ms is None:
            return "-"
        if ms < 1000:
            return "%dms" % ms
        return "%.1fs" % (ms / 1000.0)
    
    def _format_number(self, num):
        """格式化数字"""
        if num is None:
            return "-"
        return str(num)
    
    def _get_status_icon(self, status):
        """获取状态图标"""
        status_map = {
            "success": "✅",
            "failed": "❌",
            "timeout": "⏰",
        }
        return status_map.get(status, "⚪")
    
    def format_page_metrics_table(
        self, 
        page_results,
        page_names=None
    ):
        """
        格式化页面指标为表格（markdown 格式）
        
        展示：
        - 页面状态 / HTTP 状态
        - 加载时间 / DOM Ready
        - Console 错误 / 警告
        - 网络错误（4xx/5xx）
        """
        page_names = page_names or {}
        
        # 表头
        lines = [
            "📊 **页面指标详情**",
            "",
            "| 页面 | 状态 | HTTP | 加载 | DOM | 错误 | 警告 | 网络 |",
            "|------|------|------|------|-----|------|------|------|",
        ]
        
        # 数据行
        for pr in page_results:
            # 提取页面名称
            url = pr.get("url", "")
            page_name = page_names.get(url, "")
            if not page_name:
                # 从 URL 中提取简短名称
                path = url.replace("https://", "").replace("http://", "")
                parts = path.split("/")
                page_name = parts[-1] or (parts[-2] if len(parts) > 1 else path)
                page_name = page_name[:12]
            
            status_icon = self._get_status_icon(pr.get("status", "unknown"))
            http_status = pr.get("http_status", "-")
            load_time = self._format_ms(pr.get("load_time"))
            dom_ready = self._format_ms(pr.get("dom_content_loaded"))
            errors = self._format_number(pr.get("error_count"))
            warnings = self._format_number(pr.get("warning_count"))
            net_errors = self._format_number(pr.get("request_error_count"))
            
            # 高亮有问题的项
            if pr.get("error_count", 0) > 0:
                errors = "🔴" + errors
            if pr.get("warning_count", 0) > 0:
                warnings = "🟡" + warnings
            if pr.get("request_error_count", 0) > 0:
                net_errors = "🟠" + net_errors
            
            lines.append(
                "| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    page_name, status_icon, http_status, load_time, dom_ready,
                    errors, warnings, net_errors
                )
            )
        
        lines.append("")
        lines.append("**图例**: 🔴错误 | 🟡警告 | 🟠网络错误 | ✅正常")
        
        return "\n".join(lines)
    
    def format_performance_table(
        self, 
        page_results,
        page_names=None
    ):
        """
        格式化 Lighthouse 性能指标表格
        
        如果有 Lighthouse 数据，展示：
        - Performance 得分
        - Web Vitals (LCP/FID/CLS/TBT)
        - Accessibility / Best Practices / SEO 得分
        """
        page_names = page_names or {}
        
        # 检查是否有 Lighthouse 数据
        has_lighthouse = any(
            pr.get("lh_performance_score") is not None for pr in page_results
        )
        
        if not has_lighthouse:
            return ""
        
        lines = [
            "⚡ **Lighthouse 性能指标**",
            "",
            "| 页面 | Perf | A11y | Best | SEO | LCP | CLS | TBT |",
            "|------|------|------|------|-----|-----|-----|-----|",
        ]
        
        for pr in page_results:
            url = pr.get("url", "")
            page_name = page_names.get(url, url[:15])
            
            perf = pr.get("lh_performance_score", "-")
            a11y = pr.get("lh_accessibility_score", "-")
            best = pr.get("lh_best_practices_score", "-")
            seo = pr.get("lh_seo_score", "-")
            lcp = self._format_ms(pr.get("lh_lcp"))
            cls = pr.get("lh_cls", "-")
            tbt = self._format_ms(pr.get("lh_tbt"))
            
            # 颜色标记
            if perf != "-" and int(perf) < 50:
                perf = "🔴" + str(perf)
            elif perf != "-" and int(perf) < 70:
                perf = "🟡" + str(perf)
            
            lines.append(
                "| %s | %s | %s | %s | %s | %s | %s | %s |" % (
                    page_name[:10], perf, a11y, best, seo, lcp, cls, tbt
                )
            )
        
        lines.append("")
        lines.append("**Web Vitals 阈值**: LCP<2.5s ✅ | CLS<0.1 ✅ | TBT<200ms ✅")
        
        return "\n".join(lines)
    
    def format_summary_message(
        self, 
        alerts, 
        run_summary=None,
        page_results=None,
        page_names=None
    ):
        """
        格式化完整的巡检摘要消息
        
        包含：
        1. 运行摘要
        2. 告警统计
        3. 页面指标表格
        4. 详细告警列表
        """
        lines = []
        
        # 标题
        if alerts:
            lines.append("🚨 **SiteRadar 巡检告警**")
        else:
            lines.append("✅ **SiteRadar 巡检报告**")
        lines.append("")
        
        # 运行摘要
        if run_summary:
            lines.append("📋 **运行摘要**")
            lines.append("- 总页面数: %d" % run_summary.get('total_pages', 0))
            lines.append("- 成功: %d" % run_summary.get('completed_pages', 0))
            lines.append("- 失败: %d" % run_summary.get('failed_pages', 0))
            lines.append("- 耗时: %ds" % run_summary.get('duration_seconds', 0))
            lines.append("")
        
        # 告警统计
        critical = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warning = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)
        
        if critical > 0 or warning > 0:
            stats = []
            if critical > 0:
                stats.append("🔴 严重: %d" % critical)
            if warning > 0:
                stats.append("🟡 警告: %d" % warning)
            lines.append("⚠️ **告警统计**: " + " | ".join(stats))
            lines.append("")
        
        # 页面指标表格
        if page_results:
            table = self.format_page_metrics_table(page_results, page_names)
            lines.append(table)
            lines.append("")
            
            # Lighthouse 性能表格（如果有）
            perf_table = self.format_performance_table(page_results, page_names)
            if perf_table:
                lines.append(perf_table)
                lines.append("")
        
        # 详细告警列表
        if alerts:
            lines.append("📝 **详细告警**")
            lines.append("")
            for i, alert in enumerate(alerts[:10], 1):
                icon = "🔴" if alert.severity == AlertSeverity.CRITICAL else "🟡"
                lines.append("%s **%s**" % (icon, alert.page_name or '未知页面'))
                lines.append("   - 类型: %s" % alert.title)
                lines.append("   - 详情: %s..." % alert.message[:80])
                lines.append("   - URL: %s" % alert.url)
                lines.append("")
            
            if len(alerts) > 10:
                lines.append("... 还有 %d 个告警" % (len(alerts) - 10))
                lines.append("")
        
        # 时间
        lines.append("⏰ 巡检时间: %s" % datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        return "\n".join(lines)
    
    def _run_lark_cli(self, args, cwd=None):
        """运行 lark-cli 命令"""
        if not self._lark_cli_available:
            return {"ok": False, "error": "lark-cli 不可用"}
        
        try:
            cmd = [self.lark_cli] + args
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd
            )
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def send_message(self, text, chat_id=None):
        """发送纯文本消息"""
        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.error("未指定 chat_id")
            return False
        
        if not self.enabled:
            return False
        
        logger.info("📤 发送飞书消息到 %s", target_chat)
        
        if self._lark_cli_available:
            # 使用 lark-cli 发送 markdown 格式
            result = self._run_lark_cli([
                "im", "+messages-send",
                "--chat-id", target_chat,
                "--markdown", text
            ])
            
            if result["ok"]:
                logger.info("✅ 消息发送成功 (lark-cli)")
                return True
            else:
                logger.warning("lark-cli 发送失败: %s", result.get('stderr', '')[:100])
        
        return False
    
    def send_summary(
        self, 
        alerts, 
        run_summary=None,
        always_send=False,
        screenshot_paths=None,
        page_results=None,
        page_names=None,
        send_screenshots=False
    ):
        """
        发送告警摘要
        
        Args:
            alerts: 告警列表
            run_summary: 运行摘要
            always_send: 是否总是发送
            screenshot_paths: 截图路径列表（已禁用发送，保留参数兼容）
            page_results: 页面结果列表（用于表格展示）
            page_names: 页面 URL 到名称的映射
            send_screenshots: 是否发送截图（默认 false）
        """
        if not self.enabled:
            return False
        
        # 如果没有告警且不总是发送，则返回
        if not alerts and not always_send:
            logger.info("ℹ️ 无告警，跳过通知")
            return False
        
        # 生成消息
        message = self.format_summary_message(
            alerts=alerts,
            run_summary=run_summary,
            page_results=page_results,
            page_names=page_names
        )
        
        if alerts:
            logger.info("📤 发送飞书摘要: %d 个告警", len(alerts))
        else:
            logger.info("📤 发送飞书巡检报告（无告警）")
        
        # 发送消息
        return self.send_message(message)
