"""
巡检执行器 - 核心巡检逻辑
"""

import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from src.config import load_config, get_page_thresholds, GlobalConfig, PageConfig, SiteConfig
from src.database import db, Run, PageResult, ErrorRecord, RunStatus, PageResultStatus, ErrorType
from src.browser import BrowserInspector, BrowserResult
from src.alerts import AlertEngine, Alert
from src.dashboard import DashboardGenerator

logger = logging.getLogger("site-radar.checker")


class Checker:
    """巡检执行器"""
    
    def __init__(self, config: Optional[GlobalConfig] = None):
        self.config = config or load_config()
        self.alert_engine: Optional[AlertEngine] = None
        self.browser: Optional[BrowserInspector] = None
        self.current_run_id: Optional[int] = None
    
    async def run_check(
        self,
        trigger_type: str = "manual",
        specific_pages: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行一次完整的巡检
        
        Args:
            trigger_type: 触发类型 (scheduled/manual)
            specific_pages: 可选，只检查指定的页面 URL 列表
        
        Returns:
            巡检结果摘要
        """
        logger.info(f"🚀 开始巡检，触发类型: {trigger_type}")
        start_time = datetime.now()
        
        # 1. 创建运行记录
        run_uuid = str(uuid.uuid4())
        
        # 统计需要检查的页面数
        total_pages = 0
        for site in self.config.sites:
            if site.is_active:
                for page in site.pages:
                    if page.is_active:
                        # 如果指定了页面列表，检查是否包含在内
                        if specific_pages and page.url not in specific_pages:
                            continue
                        total_pages += 1
        
        run = Run(
            run_uuid=run_uuid,
            trigger_type=trigger_type,
            status=RunStatus.RUNNING,
            total_pages=total_pages,
            started_at=datetime.utcnow().isoformat()
        )
        self.current_run_id = db.create_run(run)
        
        logger.info(f"📋 运行 #{self.current_run_id} 创建完成，共 {total_pages} 个页面")
        
        # 2. 初始化告警引擎（使用全局阈值）
        self.alert_engine = AlertEngine(self.config.thresholds, self.config.error_filters)
        
        # 3. 初始化浏览器
        self.browser = BrowserInspector(
            headless=True,
            timeout=self.config.page_timeout
        )
        
        completed_pages = 0
        failed_pages = 0
        all_alerts = []
        screenshot_paths = []  # 收集所有截图路径
        errors_by_page = {}  # 按页面收集所有错误详情
        
        try:
            await self.browser.start()
            
            # 遍历所有站点
            for site in self.config.sites:
                if not site.is_active:
                    logger.info(f"⏭️  跳过禁用的站点: {site.name}")
                    continue
                
                logger.info(f"📍 检查站点: {site.name} ({site.base_url})")
                
                # 遍历站点下的所有页面
                for page in site.pages:
                    if not page.is_active:
                        logger.info(f"⏭️  跳过禁用的页面: {page.name}")
                        continue
                    
                    # 如果指定了页面列表，检查是否包含在内
                    if specific_pages and page.url not in specific_pages:
                        continue
                    
                    # 获取该页面的阈值
                    thresholds = get_page_thresholds(page, site, self.config)
                    
                    logger.info(f"🔍 检查页面: {page.name} - {page.url}")
                    
                    try:
                        # 执行浏览器巡检
                        # 使用页面配置的加载策略，默认使用 networkidle
                        wait_until = page.wait_until or "networkidle"
                        extra_wait = page.extra_wait if page.extra_wait is not None else 2000
                        
                        browser_result = await self.browser.inspect_page(
                            url=page.url,
                            capture_screenshot=page.capture_screenshot,
                            screenshot_name=page.name,
                            wait_until=wait_until,
                            extra_wait=extra_wait,
                            auth_config=page.auth_config,
                            flow_config=page.flow_config
                        )
                        
                        # 保存页面结果到数据库
                        page_result = PageResult(
                            run_id=self.current_run_id,
                            page_id=0,  # 暂时不用
                            url=page.url,
                            status=browser_result.status,
                            http_status=browser_result.http_status,
                            load_time=browser_result.load_time,
                            dom_content_loaded=browser_result.dom_content_loaded,
                            screenshot_path=browser_result.screenshot_path,
                            error_count=browser_result.error_count,
                            warning_count=browser_result.warning_count,
                            request_error_count=browser_result.request_error_count,
                            started_at=datetime.utcnow().isoformat()
                        )
                        
                        page_result_id = db.create_page_result(page_result)
                        page_result.id = page_result_id
                        
                        # 收集截图路径
                        if browser_result.screenshot_path and Path(browser_result.screenshot_path).exists():
                            screenshot_paths.append(browser_result.screenshot_path)
                            logger.debug(f"📸 收集截图: {browser_result.screenshot_path}")
                        
                        # 保存错误记录
                        error_records = self._save_errors(browser_result, page_result)
                        
                        # 收集所有错误详情（用于消息展示）
                        page_errors = []
                        for rec in error_records:
                            page_errors.append({
                                "error_type": rec.error_type,
                                "level": rec.level,
                                "message": rec.message,
                                "url": rec.url,
                                "http_status": rec.http_status,
                            })
                        if page_errors:
                            errors_by_page[page.name] = page_errors
                        
                        # 分析告警（使用该页面的阈值）
                        page_alert_engine = AlertEngine(thresholds, self.config.error_filters)
                        page_alerts = page_alert_engine.analyze_page_result(
                            page_result, error_records, page.name
                        )
                        all_alerts.extend(page_alerts)
                        
                        completed_pages += 1
                        logger.info(f"✅ 页面检查完成: {page.name}")
                        
                    except Exception as e:
                        failed_pages += 1
                        logger.error(f"❌ 页面检查失败 {page.name}: {e}")
                        
                        # 记录失败的页面结果
                        page_result = PageResult(
                            run_id=self.current_run_id,
                            url=page.url,
                            status=PageResultStatus.FAILED,
                            error_message=str(e)[:500] if str(e) else None
                        )
                        db.create_page_result(page_result)
                    
                    # 短暂延迟，避免请求过快
                    await asyncio.sleep(0.5)
            
            # 4. 更新运行状态
            run.status = RunStatus.COMPLETED
            run.completed_pages = completed_pages
            run.failed_pages = failed_pages
            run.completed_at = datetime.utcnow().isoformat()
            run.id = self.current_run_id
            db.update_run(run)
            
            # 5. 生成仪表盘
            logger.info("📊 生成仪表盘...")
            dashboard_gen = DashboardGenerator()
            dashboard_path = dashboard_gen.generate()
            
            # 6. 计算执行时间
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # 7. 获取告警摘要
            alert_summary = self.alert_engine.get_summary() if self.alert_engine else {"total": 0}
            
            result = {
                "run_id": self.current_run_id,
                "run_uuid": run_uuid,
                "status": "completed",
                "total_pages": total_pages,
                "completed_pages": completed_pages,
                "failed_pages": failed_pages,
                "duration_seconds": round(duration, 2),
                "dashboard_path": dashboard_path,
                "alerts": alert_summary,
                "screenshot_paths": screenshot_paths,
                "errors_by_page": errors_by_page,  # 所有错误详情
                "alert_list": [
                    {
                        "type": a.alert_type,
                        "severity": a.severity,
                        "title": a.title,
                        "message": a.message,
                        "url": a.url,
                        "page_name": a.page_name
                    }
                    for a in all_alerts
                ]
            }
            
            logger.info(f"✅ 巡检完成: {completed_pages} 成功, {failed_pages} 失败, 耗时 {duration:.2f}s")
            logger.info(f"📊 仪表盘: {dashboard_path}")
            logger.info(f"⚠️  告警数: {alert_summary}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ 巡检执行失败: {e}")
            
            # 更新运行状态为失败
            run.status = RunStatus.FAILED
            run.error_message = str(e)[:500]
            run.id = self.current_run_id
            db.update_run(run)
            
            raise
    
    def _save_errors(self, browser_result: BrowserResult, page_result: PageResult) -> List[ErrorRecord]:
        """保存错误记录"""
        records = []
        
        # Console Errors
        for err in browser_result.console_errors:
            record = ErrorRecord(
                page_result_id=page_result.id or 0,
                run_id=self.current_run_id or 0,
                error_type=ErrorType.CONSOLE,
                level="error",
                message=err.text,
                source=err.location,
                occurred_at=err.timestamp
            )
            record.id = db.create_error(record)
            records.append(record)
        
        # Console Warnings
        for warn in browser_result.console_warnings:
            record = ErrorRecord(
                page_result_id=page_result.id or 0,
                run_id=self.current_run_id or 0,
                error_type=ErrorType.CONSOLE,
                level="warning",
                message=warn.text,
                source=warn.location,
                occurred_at=warn.timestamp
            )
            record.id = db.create_error(record)
            records.append(record)
        
        # Page Exceptions
        for exc in browser_result.page_exceptions:
            record = ErrorRecord(
                page_result_id=page_result.id or 0,
                run_id=self.current_run_id or 0,
                error_type=ErrorType.EXCEPTION,
                level="error",
                message=exc.message,
                stack_trace=exc.stack,
                occurred_at=exc.timestamp
            )
            record.id = db.create_error(record)
            records.append(record)
        
        # Network Errors
        for net_err in browser_result.network_errors:
            record = ErrorRecord(
                page_result_id=page_result.id or 0,
                run_id=self.current_run_id or 0,
                error_type=ErrorType.NETWORK,
                level="error" if net_err.status >= 500 else "warning",
                message=f"HTTP {net_err.status} {net_err.method}",
                url=net_err.url,
                http_status=net_err.status,
                occurred_at=net_err.timestamp
            )
            record.id = db.create_error(record)
            records.append(record)
        
        return records
    
    async def close(self):
        """关闭资源"""
        if self.browser:
            await self.browser.stop()


async def run_check_async(
    trigger_type: str = "manual",
    specific_pages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """异步执行巡检的便捷函数"""
    checker = Checker()
    try:
        return await checker.run_check(trigger_type, specific_pages)
    finally:
        await checker.close()


def run_check(
    trigger_type: str = "manual",
    specific_pages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """同步执行巡检的便捷函数"""
    return asyncio.run(run_check_async(trigger_type, specific_pages))
