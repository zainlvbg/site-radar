"""
飞书告警模块 - 集成 lark-cli 发送消息和图片
"""

import logging
import os
import subprocess
import shutil
from typing import List, Optional
from datetime import datetime
from pathlib import Path

from src.alerts import Alert, AlertSeverity

logger = logging.getLogger("site-radar.feishu")


class FeishuNotifier:
    """飞书通知器"""
    
    def __init__(
        self, 
        enabled: bool = True,
        chat_id: Optional[str] = None,
        lark_cli_path: Optional[str] = None
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
        
        logger.info(f"飞书通知器初始化: enabled={enabled}, chat_id={chat_id}, lark_cli={self.lark_cli}, available={self._lark_cli_available}")
    
    def _find_lark_cli(self) -> Optional[str]:
        """查找 lark-cli 可执行文件"""
        # 常见路径
        possible_paths = [
            "/Users/frontend/.local/bin/lark-cli",
            "/opt/homebrew/lib/node_modules/@larksuite/cli/scripts/run.js",
            "lark-cli",
        ]
        
        # 检查 PATH 中的 lark-cli
        if shutil.which("lark-cli"):
            return "lark-cli"
        
        # 检查固定路径
        for path in possible_paths:
            if os.path.exists(path) and os.access(path, os.X_OK):
                return path
        
        return None
    
    def _check_lark_cli(self) -> bool:
        """检查 lark-cli 是否可用"""
        try:
            result = subprocess.run(
                [self.lark_cli, "--help"],
                capture_output=True,
                text=True,
                timeout=10
            )
            return result.returncode == 0
        except Exception as e:
            logger.warning(f"lark-cli 检查失败: {e}")
            return False
    
    def format_alert_message(self, alert: Alert) -> str:
        """格式化单个告警为飞书消息"""
        
        # 图标映射
        severity_icons = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵"
        }
        
        icon = severity_icons.get(alert.severity, "⚪")
        
        lines = [
            f"{icon} **{alert.title}**",
            f"",
            f"**页面**: {alert.page_name or '未知页面'}",
            f"**URL**: {alert.url}",
            f"",
            f"**详情**: {alert.message}",
        ]
        
        if alert.page_result_id:
            lines.append(f"**结果 ID**: #{alert.page_result_id}")
        
        lines.append(f"**时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        return "\n".join(lines)
    
    def format_summary_message(
        self, 
        alerts: List[Alert], 
        run_summary: dict = None
    ) -> str:
        """格式化告警摘要消息"""
        
        # 统计
        critical = sum(1 for a in alerts if a.severity == AlertSeverity.CRITICAL)
        warning = sum(1 for a in alerts if a.severity == AlertSeverity.WARNING)
        info = sum(1 for a in alerts if a.severity == AlertSeverity.INFO)
        
        lines = [
            "🚨 **SiteRadar 巡检告警**",
            "",
        ]
        
        # 摘要统计
        stats_parts = []
        if critical > 0:
            stats_parts.append(f"🔴 严重: {critical}")
        if warning > 0:
            stats_parts.append(f"🟡 警告: {warning}")
        if info > 0:
            stats_parts.append(f"🔵 信息: {info}")
        
        if stats_parts:
            lines.append(" | ".join(stats_parts))
        else:
            lines.append("✅ 无告警")
        
        lines.append("")
        
        # 运行摘要
        if run_summary:
            lines.append(f"📊 **巡检摘要**")
            lines.append(f"   总页面数: {run_summary.get('total_pages', 0)}")
            lines.append(f"   成功: {run_summary.get('completed_pages', 0)}")
            lines.append(f"   失败: {run_summary.get('failed_pages', 0)}")
            lines.append(f"   耗时: {run_summary.get('duration_seconds', 0)}s")
            lines.append("")
        
        # 详细告警列表
        if alerts:
            lines.append("📋 **告警详情**:")
            lines.append("")
            
            for i, alert in enumerate(alerts[:10], 1):  # 最多显示 10 个
                icon = "🔴" if alert.severity == AlertSeverity.CRITICAL else "🟡"
                lines.append(f"{i}. {icon} **{alert.page_name or '未知'}**")
                lines.append(f"   {alert.title}")
                lines.append(f"   {alert.message[:100]}..." if len(alert.message) > 100 else f"   {alert.message}")
                lines.append(f"   URL: {alert.url}")
                lines.append("")
            
            if len(alerts) > 10:
                lines.append(f"... 还有 {len(alerts) - 10} 个告警")
        
        return "\n".join(lines)
    
    def _run_lark_cli(self, args: List[str], cwd: Optional[str] = None) -> dict:
        """运行 lark-cli 命令"""
        if not self._lark_cli_available:
            return {"ok": False, "error": "lark-cli 不可用"}
        
        try:
            cmd = [self.lark_cli] + args
            logger.debug(f"运行 lark-cli: {' '.join(cmd)} (cwd={cwd})")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                cwd=cwd
            )
            
            logger.debug(f"lark-cli 返回: returncode={result.returncode}")
            logger.debug(f"stdout: {result.stdout}")
            if result.stderr:
                logger.debug(f"stderr: {result.stderr}")
            
            return {
                "ok": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
            
        except subprocess.TimeoutExpired:
            logger.error("lark-cli 命令超时")
            return {"ok": False, "error": "命令超时"}
        except Exception as e:
            logger.error(f"lark-cli 命令失败: {e}")
            return {"ok": False, "error": str(e)}
    
    def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        """
        发送纯文本消息
        
        Args:
            text: 消息内容
            chat_id: 目标聊天 ID，默认使用初始化时的 chat_id
            
        Returns:
            是否发送成功
        """
        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.error("未指定 chat_id")
            return False
        
        if not self.enabled:
            logger.debug("飞书告警已禁用")
            return False
        
        logger.info(f"📤 发送飞书消息到 {target_chat}")
        
        # 优先使用 lark-cli
        if self._lark_cli_available:
            result = self._run_lark_cli([
                "im", "+messages-send",
                "--chat-id", target_chat,
                "--text", text
            ])
            
            if result["ok"]:
                logger.info("✅ 消息发送成功 (lark-cli)")
                return True
            else:
                logger.warning(f"lark-cli 发送失败: {result.get('error') or result.get('stderr')}，返回消息内容供后续处理")
        
        # lark-cli 不可用时，返回消息内容供调用方使用 send_message 工具
        logger.info("返回消息内容供 send_message 工具发送")
        return True  # 返回 True 表示消息已准备好
    
    def send_image(
        self, 
        image_path: str, 
        text: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> bool:
        """
        发送图片消息
        
        Args:
            image_path: 图片路径（绝对路径或相对路径）
            text: 可选的文字说明
            chat_id: 目标聊天 ID
            
        Returns:
            是否发送成功
        """
        target_chat = chat_id or self.chat_id
        if not target_chat:
            logger.error("未指定 chat_id")
            return False
        
        if not self.enabled:
            logger.debug("飞书告警已禁用")
            return False
        
        if not self._lark_cli_available:
            logger.error("lark-cli 不可用，无法发送图片")
            return False
        
        # 检查图片文件
        image_path = os.path.abspath(image_path)
        if not os.path.exists(image_path):
            logger.error(f"图片文件不存在: {image_path}")
            return False
        
        logger.info(f"📤 发送图片: {image_path}")
        
        # 获取图片所在目录和文件名（lark-cli 需要相对路径）
        image_dir = os.path.dirname(image_path)
        image_filename = os.path.basename(image_path)
        
        # 构建命令参数
        args = [
            "im", "+messages-send",
            "--chat-id", target_chat,
            "--image", f"./{image_filename}"
        ]
        
        # 发送图片
        result = self._run_lark_cli(args, cwd=image_dir)
        
        if result["ok"]:
            logger.info(f"✅ 图片发送成功: {image_filename}")
            
            # 如果有文字说明，再发送一条文字消息
            if text:
                self.send_message(text, target_chat)
            
            return True
        else:
            logger.error(f"❌ 图片发送失败: {result.get('error') or result.get('stderr')}")
            return False
    
    def send_multiple_images(
        self,
        image_paths: List[str],
        text: Optional[str] = None,
        chat_id: Optional[str] = None
    ) -> int:
        """
        发送多张图片
        
        Args:
            image_paths: 图片路径列表
            text: 可选的文字说明
            chat_id: 目标聊天 ID
            
        Returns:
            成功发送的图片数量
        """
        if not image_paths:
            return 0
        
        success_count = 0
        
        # 先发送文字说明（如果有）
        if text:
            if self.send_message(text, chat_id):
                pass  # 成功发送
        
        # 逐个发送图片
        for image_path in image_paths:
            if self.send_image(image_path, chat_id=chat_id):
                success_count += 1
        
        return success_count
    
    def send_alert(self, alert: Alert, screenshot_path: Optional[str] = None) -> bool:
        """
        发送单个告警到飞书
        
        Args:
            alert: 告警对象
            screenshot_path: 可选的截图路径
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            logger.debug("飞书告警已禁用")
            return False
        
        message = self.format_alert_message(alert)
        logger.info(f"📤 发送飞书告警: {alert.title}")
        
        # 发送文字消息
        success = self.send_message(message)
        
        # 如果有截图，发送截图
        if screenshot_path and os.path.exists(screenshot_path):
            self.send_image(screenshot_path, f"📸 {alert.page_name or '截图'}")
        
        return success
    
    def send_summary(
        self, 
        alerts: List[Alert], 
        run_summary: dict = None,
        always_send: bool = False,
        screenshot_paths: Optional[List[str]] = None
    ) -> bool:
        """
        发送告警摘要
        
        Args:
            alerts: 告警列表
            run_summary: 运行摘要
            always_send: 是否总是发送（即使没有告警）
            screenshot_paths: 截图路径列表
            
        Returns:
            是否发送成功
        """
        if not self.enabled:
            return False
        
        # 如果没有告警且不总是发送，则返回
        if not alerts and not always_send:
            logger.info("ℹ️  无告警，跳过飞书通知")
            return False
        
        message = self.format_summary_message(alerts, run_summary)
        
        if alerts:
            logger.info(f"📤 发送飞书摘要: {len(alerts)} 个告警")
        else:
            logger.info(f"📤 发送飞书巡检报告（无告警）")
        
        # 发送文字消息
        success = self.send_message(message)
        
        # 发送截图（最多发送 5 张，避免消息过多）
        if screenshot_paths:
            max_screenshots = min(len(screenshot_paths), 5)
            sent = self.send_multiple_images(
                screenshot_paths[:max_screenshots],
                chat_id=self.chat_id
            )
            logger.info(f"📸 发送了 {sent}/{max_screenshots} 张截图")
        
        return success
