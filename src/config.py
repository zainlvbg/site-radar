"""
配置加载模块
"""

import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
import logging

from src import CONFIG_PATH, SITES_DIR, DEFAULT_THRESHOLDS

logger = logging.getLogger("site-radar.config")


@dataclass
class AlertThresholds:
    """告警阈值配置"""
    # 性能告警
    critical_score: int = 50
    warning_score: int = 70
    score_drop_single: int = 10
    score_drop_consecutive: int = 3
    lcp_critical: int = 4000
    lcp_warning: int = 2500
    cls_critical: float = 0.25
    cls_warning: float = 0.1
    tbt_critical: int = 600
    tbt_warning: int = 200
    load_time_warning: int = 5000
    load_time_critical: int = 10000
    
    # 错误告警
    alert_on_console_error: bool = True
    alert_on_js_exception: bool = True
    alert_on_network_5xx: bool = True
    alert_on_network_4xx: bool = False


@dataclass
class ErrorFilters:
    """错误过滤配置"""
    # Console 错误忽略模式（文本包含匹配）
    console_ignore_patterns: List[str] = field(default_factory=list)
    
    # 网络错误忽略模式
    network_ignore_patterns: List[str] = field(default_factory=list)
    
    # 超时忽略的 URL 模式
    timeout_ignore_urls: List[str] = field(default_factory=list)
    
    def should_ignore_console_error(self, message: str) -> bool:
        """检查 Console 错误是否应该被忽略"""
        if not message:
            return False
        message_lower = message.lower()
        for pattern in self.console_ignore_patterns:
            if pattern.lower() in message_lower:
                return True
        return False
    
    def should_ignore_network_error(self, url: str, status: int) -> bool:
        """检查网络错误是否应该被忽略"""
        url_str = str(url or "")
        for pattern in self.network_ignore_patterns:
            if pattern in url_str:
                return True
        return False
    
    def should_ignore_timeout(self, url: str) -> bool:
        """检查超时是否应该被忽略"""
        for pattern in self.timeout_ignore_urls:
            if pattern in url:
                return True
        return False


@dataclass
class PageConfig:
    """页面配置"""
    name: str
    url: str
    path: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    is_active: bool = True
    
    # 检查项开关
    check_performance: bool = True
    check_errors: bool = True
    capture_screenshot: bool = True
    
    # 加载策略
    wait_until: Optional[str] = None  # load / domcontentloaded / networkidle
    extra_wait: Optional[int] = None   # 额外等待时间 (ms)
    
    # 登录态配置（JSON）
    auth_config: Optional[Dict[str, Any]] = None
    
    # 业务流程配置（JSON）
    flow_config: Optional[Dict[str, Any]] = None
    
    # 覆盖阈值
    thresholds: Optional[Dict[str, Any]] = None


@dataclass
class SiteConfig:
    """站点配置"""
    name: str
    base_url: str
    tags: List[str] = field(default_factory=list)
    is_active: bool = True
    pages: List[PageConfig] = field(default_factory=list)
    thresholds: Optional[Dict[str, Any]] = None


@dataclass
class FeishuConfig:
    """飞书告警配置"""
    chat_id: Optional[str] = None
    send_screenshots: bool = True
    max_screenshots: int = 5


@dataclass
class GlobalConfig:
    """全局配置"""
    # 巡检配置
    schedule: str = "0 */2 * * *"  # 默认每 2 小时
    max_concurrent: int = 3  # 最大并发数
    page_timeout: int = 60000  # 页面超时时间 (ms)
    
    # 告警配置
    alert_channels: List[str] = field(default_factory=lambda: ["feishu"])
    
    # 飞书配置
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    
    # 全局阈值
    thresholds: AlertThresholds = field(default_factory=AlertThresholds)
    
    # 错误过滤
    error_filters: ErrorFilters = field(default_factory=ErrorFilters)
    
    # 站点列表
    sites: List[SiteConfig] = field(default_factory=list)


def load_yaml(path: Path) -> Dict[str, Any]:
    """加载 YAML 文件"""
    if not path.exists():
        logger.warning(f"配置文件不存在: {path}")
        return {}
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        logger.info(f"✅ 加载配置: {path}")
        return data
    except Exception as e:
        logger.error(f"❌ 加载配置失败 {path}: {e}")
        return {}


def parse_page_config(page_data: Dict[str, Any], site_base_url: str) -> PageConfig:
    """解析页面配置"""
    # 构建完整 URL
    path = page_data.get("path")
    url = page_data.get("url")
    if not url and path:
        url = site_base_url.rstrip("/") + "/" + path.lstrip("/")
    
    return PageConfig(
        name=page_data.get("name", url or "Unknown"),
        url=url or "",
        path=path,
        tags=page_data.get("tags", []),
        is_active=page_data.get("is_active", True),
        check_performance=page_data.get("check_performance", True),
        check_errors=page_data.get("check_errors", True),
        capture_screenshot=page_data.get("capture_screenshot", True),
        wait_until=page_data.get("wait_until"),
        extra_wait=page_data.get("extra_wait"),
        auth_config=page_data.get("auth"),
        flow_config=page_data.get("flow"),
        thresholds=page_data.get("thresholds"),
    )


def parse_site_config(site_data: Dict[str, Any]) -> SiteConfig:
    """解析站点配置"""
    base_url = site_data.get("base_url", "")
    
    # 解析页面列表
    pages_data = site_data.get("pages", [])
    pages = [parse_page_config(p, base_url) for p in pages_data]
    
    return SiteConfig(
        name=site_data.get("name", base_url),
        base_url=base_url,
        tags=site_data.get("tags", []),
        is_active=site_data.get("is_active", True),
        pages=pages,
        thresholds=site_data.get("thresholds"),
    )


def parse_thresholds(thresholds_data: Dict[str, Any]) -> AlertThresholds:
    """解析阈值配置"""
    perf = thresholds_data.get("performance", {})
    errors = thresholds_data.get("errors", {})
    
    return AlertThresholds(
        # 性能阈值
        critical_score=perf.get("critical_score", DEFAULT_THRESHOLDS["performance"]["critical_score"]),
        warning_score=perf.get("warning_score", DEFAULT_THRESHOLDS["performance"]["warning_score"]),
        score_drop_single=perf.get("score_drop_single", DEFAULT_THRESHOLDS["performance"]["score_drop_single"]),
        score_drop_consecutive=perf.get("score_drop_consecutive", DEFAULT_THRESHOLDS["performance"]["score_drop_consecutive"]),
        lcp_critical=perf.get("lcp_critical", DEFAULT_THRESHOLDS["performance"]["lcp_critical"]),
        lcp_warning=perf.get("lcp_warning", DEFAULT_THRESHOLDS["performance"]["lcp_warning"]),
        cls_critical=perf.get("cls_critical", DEFAULT_THRESHOLDS["performance"]["cls_critical"]),
        cls_warning=perf.get("cls_warning", DEFAULT_THRESHOLDS["performance"]["cls_warning"]),
        tbt_critical=perf.get("tbt_critical", DEFAULT_THRESHOLDS["performance"]["tbt_critical"]),
        tbt_warning=perf.get("tbt_warning", DEFAULT_THRESHOLDS["performance"]["tbt_warning"]),
        load_time_warning=perf.get("load_time_warning", DEFAULT_THRESHOLDS["performance"]["load_time_warning"]),
        load_time_critical=perf.get("load_time_critical", DEFAULT_THRESHOLDS["performance"]["load_time_critical"]),
        # 错误阈值
        alert_on_console_error=errors.get("alert_on_console_error", DEFAULT_THRESHOLDS["errors"]["alert_on_console_error"]),
        alert_on_js_exception=errors.get("alert_on_js_exception", DEFAULT_THRESHOLDS["errors"]["alert_on_js_exception"]),
        alert_on_network_5xx=errors.get("alert_on_network_5xx", DEFAULT_THRESHOLDS["errors"]["alert_on_network_5xx"]),
        alert_on_network_4xx=errors.get("alert_on_network_4xx", DEFAULT_THRESHOLDS["errors"]["alert_on_network_4xx"]),
    )


def load_config() -> GlobalConfig:
    """加载全局配置"""
    config = GlobalConfig()
    
    # 1. 加载主配置文件
    main_data = load_yaml(CONFIG_PATH)
    
    # 2. 加载全局设置
    config.schedule = main_data.get("schedule", config.schedule)
    config.max_concurrent = main_data.get("max_concurrent", config.max_concurrent)
    config.page_timeout = main_data.get("page_timeout", config.page_timeout)
    config.alert_channels = main_data.get("alert_channels", config.alert_channels)
    
    # 3. 加载飞书配置
    if "feishu" in main_data:
        feishu_data = main_data["feishu"]
        config.feishu = FeishuConfig(
            chat_id=feishu_data.get("chat_id"),
            send_screenshots=feishu_data.get("send_screenshots", True),
            max_screenshots=feishu_data.get("max_screenshots", 5),
        )
        logger.info(f"📱 飞书配置: chat_id={config.feishu.chat_id}, send_screenshots={config.feishu.send_screenshots}")
    
    # 4. 加载全局阈值
    if "thresholds" in main_data:
        config.thresholds = parse_thresholds(main_data["thresholds"])
    
    # 5. 加载错误过滤配置
    if "error_filters" in main_data:
        filters = main_data["error_filters"]
        config.error_filters = ErrorFilters(
            console_ignore_patterns=filters.get("console_ignore_patterns", []),
            network_ignore_patterns=filters.get("network_ignore_patterns", []),
            timeout_ignore_urls=filters.get("timeout_ignore_urls", []),
        )
    
    # 6. 加载主配置中的站点
    sites_data = main_data.get("sites", [])
    
    # 7. 加载 sites/ 目录下的站点配置
    if SITES_DIR.exists():
        for site_file in SITES_DIR.glob("*.yaml"):
            site_data = load_yaml(site_file)
            if site_data:
                sites_data.append(site_data)
    
    # 8. 解析所有站点
    config.sites = [parse_site_config(s) for s in sites_data]
    
    logger.info(f"📋 配置加载完成: {len(config.sites)} 个站点")
    
    # 统计页面数
    total_pages = sum(len(s.pages) for s in config.sites if s.is_active)
    active_sites = sum(1 for s in config.sites if s.is_active)
    logger.info(f"📊 激活: {active_sites} 个站点, {total_pages} 个页面")
    
    return config


def get_page_thresholds(page: PageConfig, site: SiteConfig, global_config: GlobalConfig) -> AlertThresholds:
    """获取页面的最终阈值（优先级：页面 > 站点 > 全局）"""
    # 检查页面级阈值
    if page.thresholds:
        return parse_thresholds(page.thresholds)
    
    # 检查站点级阈值
    if site.thresholds:
        return parse_thresholds(site.thresholds)
    
    # 使用全局阈值
    return global_config.thresholds
