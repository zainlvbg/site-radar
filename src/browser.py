"""
浏览器封装模块 - Playwright
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
import logging
import re

from playwright.async_api import async_playwright, Page, Browser, BrowserContext, Response, ConsoleMessage, Error
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from src import SCREENSHOTS_DIR

logger = logging.getLogger("site-radar.browser")


@dataclass
class ConsoleError:
    """Console 错误记录"""
    type: str  # error / warning / info / log
    text: str
    location: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class NetworkError:
    """网络请求错误"""
    url: str
    status: int
    method: str
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PageException:
    """页面异常"""
    message: str
    stack: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class BrowserResult:
    """浏览器检查结果"""
    # 页面状态
    url: str
    status: str = "success"  # success / failed / timeout
    http_status: Optional[int] = None
    
    # 时间指标
    load_time: Optional[int] = None  # ms
    dom_content_loaded: Optional[int] = None  # ms
    
    # 错误收集
    console_errors: List[ConsoleError] = field(default_factory=list)
    console_warnings: List[ConsoleError] = field(default_factory=list)
    network_errors: List[NetworkError] = field(default_factory=list)
    page_exceptions: List[PageException] = field(default_factory=list)
    
    # 截图
    screenshot_path: Optional[str] = None
    
    # 原始性能数据
    performance_timing: Optional[Dict[str, Any]] = None
    
    # 错误信息
    error_message: Optional[str] = None


class BrowserInspector:
    """浏览器巡检器"""
    
    def __init__(
        self,
        headless: bool = True,
        timeout: int = 60000,  # ms
        viewport: Dict[str, int] = None,
        user_agent: str = None,
    ):
        self.headless = headless
        self.timeout = timeout
        self.viewport = viewport or {"width": 1920, "height": 1080}
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 SiteRadar/1.0"
        )
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
    
    async def start(self):
        """启动浏览器"""
        logger.info("🚀 启动浏览器...")
        self.playwright = await async_playwright().start()
        
        # 启动 Chromium
        self.browser = await self.playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
                '--no-sandbox',
                '--disable-gpu',
            ]
        )
        
        # 创建上下文
        self.context = await self.browser.new_context(
            viewport=self.viewport,
            user_agent=self.user_agent,
            locale='zh-CN',
            timezone_id='Asia/Shanghai',
        )
        
        # 设置默认超时
        self.context.set_default_timeout(self.timeout)
        
        logger.info(f"✅ 浏览器已启动: Chromium (headless={self.headless})")
    
    async def stop(self):
        """停止浏览器"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if hasattr(self, 'playwright'):
            await self.playwright.stop()
        logger.info("🛑 浏览器已关闭")
    
    async def inspect_page(
        self, 
        url: str,
        capture_screenshot: bool = True,
        screenshot_name: Optional[str] = None,
        wait_until: str = "networkidle",  # load / domcontentloaded / networkidle / commit
        extra_wait: int = 2000,  # 额外等待时间（ms）
        auth_config: Optional[Dict[str, Any]] = None,
        flow_config: Optional[Dict[str, Any]] = None,
    ) -> BrowserResult:
        """
        巡检单个页面
        
        Args:
            url: 页面 URL
            capture_screenshot: 是否截图
            screenshot_name: 截图文件名（不含路径和后缀）
            wait_until: 等待条件
            extra_wait: 额外等待时间
            auth_config: 登录态配置
            flow_config: 业务流程配置
        """
        result = BrowserResult(url=url)
        
        if not self.context:
            result.status = "failed"
            result.error_message = "浏览器上下文未初始化"
            return result
        
        try:
            page = await self.context.new_page()
            
            # 收集 Console 消息
            console_errors: List[ConsoleError] = []
            console_warnings: List[ConsoleError] = []
            
            def handle_console(msg: ConsoleMessage):
                try:
                    location = msg.location
                    location_str = f"{location.get('url', '')}:{location.get('lineNumber', 0)}" if location else None
                    
                    error = ConsoleError(
                        type=msg.type,
                        text=msg.text,
                        location=location_str
                    )
                    
                    if msg.type == "error":
                        console_errors.append(error)
                        logger.warning(f"⚠️ Console Error: {msg.text}")
                    elif msg.type == "warning":
                        console_warnings.append(error)
                        logger.debug(f"⚠️ Console Warning: {msg.text}")
                except Exception as e:
                    logger.debug(f"处理 Console 消息出错: {e}")
            
            page.on("console", handle_console)
            
            # 收集页面异常
            page_exceptions: List[PageException] = []
            
            def handle_pageerror(error: Error):
                try:
                    exc = PageException(
                        message=error.message,
                        stack=error.stack
                    )
                    page_exceptions.append(exc)
                    logger.error(f"💥 Page Exception: {error.message}")
                except Exception as e:
                    logger.debug(f"处理页面异常出错: {e}")
            
            page.on("pageerror", handle_pageerror)
            
            # 收集网络错误
            network_errors: List[NetworkError] = []
            
            def handle_response(response: Response):
                try:
                    status = response.status
                    if 400 <= status < 600:
                        error = NetworkError(
                            url=response.url,
                            status=status,
                            method=response.request.method
                        )
                        network_errors.append(error)
                        
                        level = logger.warning if status < 500 else logger.error
                        level(f"🌐 Network Error: {status} {response.request.method} {response.url}")
                except Exception as e:
                    logger.debug(f"处理响应出错: {e}")
            
            page.on("response", handle_response)
            
            # 执行登录态配置
            if auth_config:
                await self._apply_auth_config(page, auth_config)
            
            # 导航到页面
            logger.info(f"🌐 访问页面: {url}")
            start_time = datetime.now()
            
            response = await page.goto(
                url,
                wait_until=wait_until,
                timeout=self.timeout
            )
            
            # 额外等待，确保页面稳定
            if extra_wait > 0:
                await asyncio.sleep(extra_wait / 1000)
            
            end_time = datetime.now()
            
            # HTTP 状态码
            if response:
                result.http_status = response.status
                logger.info(f"📊 HTTP 状态: {response.status}")
            
            # 计算加载时间
            result.load_time = int((end_time - start_time).total_seconds() * 1000)
            
            # 获取性能指标
            try:
                perf_timing = await page.evaluate("""
                    () => {
                        const timing = performance.timing;
                        return {
                            navigationStart: timing.navigationStart,
                            domContentLoadedEventStart: timing.domContentLoadedEventStart,
                            domContentLoadedEventEnd: timing.domContentLoadedEventEnd,
                            loadEventStart: timing.loadEventStart,
                            loadEventEnd: timing.loadEventEnd,
                            domInteractive: timing.domInteractive,
                            responseStart: timing.responseStart,
                            responseEnd: timing.responseEnd,
                        };
                    }
                """)
                
                result.performance_timing = perf_timing
                
                # 计算 DOM Content Loaded 时间
                if perf_timing.get('domContentLoadedEventEnd') and perf_timing.get('navigationStart'):
                    result.dom_content_loaded = (
                        perf_timing['domContentLoadedEventEnd'] - perf_timing['navigationStart']
                    )
                
                logger.info(f"⏱️  加载时间: {result.load_time}ms, DOM Ready: {result.dom_content_loaded}ms")
                
            except Exception as e:
                logger.debug(f"获取性能指标出错: {e}")
            
            # 执行自定义业务流程
            if flow_config:
                await self._execute_flow(page, flow_config, result)
            
            # 截图
            if capture_screenshot:
                screenshot_path = await self._take_screenshot(page, screenshot_name or self._url_to_filename(url))
                result.screenshot_path = screenshot_path
                logger.info(f"📸 截图已保存: {screenshot_path}")
            
            # 收集结果
            result.console_errors = console_errors
            result.console_warnings = console_warnings
            result.network_errors = network_errors
            result.page_exceptions = page_exceptions
            
            result.error_count = len(console_errors) + len(page_exceptions)
            result.warning_count = len(console_warnings)
            result.request_error_count = len(network_errors)
            
            logger.info(
                f"✅ 页面巡检完成: "
                f"{result.error_count} 错误, "
                f"{result.warning_count} 警告, "
                f"{result.request_error_count} 网络错误"
            )
            
            # 关闭页面
            await page.close()
            
        except PlaywrightTimeoutError as e:
            result.status = "timeout"
            result.error_message = f"页面加载超时 ({self.timeout}ms)"
            logger.error(f"⏰ 页面超时: {url}")
            
        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)
            logger.error(f"❌ 页面巡检失败: {url} - {e}")
        
        return result
    
    async def _apply_auth_config(self, page: Page, auth_config: Dict[str, Any]):
        """应用登录态配置"""
        logger.info(f"🔐 应用登录态配置...")
        
        # 方式 1: 设置 Cookie
        if "cookies" in auth_config:
            cookies = auth_config["cookies"]
            if isinstance(cookies, list):
                await self.context.add_cookies(cookies)
                logger.info(f"✅ 已设置 {len(cookies)} 个 Cookie")
        
        # 方式 2: 执行登录脚本
        if "login_script" in auth_config:
            script = auth_config["login_script"]
            try:
                await page.evaluate(script)
                logger.info("✅ 已执行登录脚本")
            except Exception as e:
                logger.error(f"❌ 登录脚本执行失败: {e}")
        
        # 方式 3: 存储状态 (localStorage/sessionStorage)
        if "storage" in auth_config:
            storage = auth_config["storage"]
            for key, value in storage.get("localStorage", {}).items():
                await page.evaluate(f"localStorage.setItem('{key}', '{value}')")
            logger.info("✅ 已设置 Storage")
    
    async def _execute_flow(self, page: Page, flow_config: Dict[str, Any], result: BrowserResult):
        """执行自定义业务流程"""
        logger.info(f"🎬 执行业务流程...")
        
        steps = flow_config.get("steps", [])
        
        for i, step in enumerate(steps):
            step_type = step.get("type")
            logger.info(f"   步骤 {i+1}: {step_type}")
            
            try:
                if step_type == "click":
                    selector = step.get("selector")
                    if selector:
                        await page.click(selector)
                        await page.wait_for_load_state("networkidle")
                
                elif step_type == "fill":
                    selector = step.get("selector")
                    value = step.get("value")
                    if selector and value:
                        await page.fill(selector, value)
                
                elif step_type == "press":
                    key = step.get("key")
                    if key:
                        await page.keyboard.press(key)
                        await page.wait_for_load_state("networkidle")
                
                elif step_type == "wait":
                    duration = step.get("duration", 1000)
                    await asyncio.sleep(duration / 1000)
                
                elif step_type == "wait_for_selector":
                    selector = step.get("selector")
                    if selector:
                        await page.wait_for_selector(selector, timeout=step.get("timeout", 5000))
                
                elif step_type == "assert":
                    # 执行断言
                    condition = step.get("condition")
                    if condition == "visible":
                        selector = step.get("selector")
                        if selector:
                            is_visible = await page.is_visible(selector)
                            if not is_visible:
                                logger.warning(f"⚠️ 断言失败: 选择器 {selector} 不可见")
                
                elif step_type == "screenshot":
                    name = step.get("name", f"flow-step-{i}")
                    await self._take_screenshot(page, name)
                
            except Exception as e:
                logger.error(f"❌ 步骤 {i+1} 执行失败: {e}")
    
    async def _take_screenshot(self, page: Page, name: str) -> str:
        """截图并保存"""
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        filename = f"{name}-{timestamp}.png"
        
        # 按日期分类存储
        date_dir = SCREENSHOTS_DIR / datetime.now().strftime("%Y-%m-%d")
        date_dir.mkdir(parents=True, exist_ok=True)
        
        filepath = date_dir / filename
        
        await page.screenshot(
            path=str(filepath),
            full_page=True,
            type="png"
        )
        
        return str(filepath)
    
    def _url_to_filename(self, url: str) -> str:
        """将 URL 转换为安全的文件名"""
        # 移除协议
        name = re.sub(r'^https?://', '', url)
        # 替换非法字符
        name = re.sub(r'[^\w\-]', '-', name)
        # 截断过长的名称
        return name[:50]


# 便捷函数
async def inspect_url(
    url: str,
    headless: bool = True,
    timeout: int = 60000,
    **kwargs
) -> BrowserResult:
    """便捷函数：巡检单个 URL"""
    async with BrowserInspector(headless=headless, timeout=timeout) as inspector:
        return await inspector.inspect_page(url, **kwargs)
