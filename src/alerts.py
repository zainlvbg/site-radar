"""
告警引擎模块
"""

from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from enum import Enum
import logging

from src.config import AlertThresholds
from src.database import PageResult, ErrorRecord, db

logger = logging.getLogger("site-radar.alerts")


class AlertSeverity(str, Enum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class AlertType(str, Enum):
    # 可用性
    SITE_DOWN = "site_down"
    
    # 性能
    PERFORMANCE_CRITICAL = "performance_critical"
    PERFORMANCE_WARNING = "performance_warning"
    SCORE_DROP = "score_drop"
    LCP_EXCEEDED = "lcp_exceeded"
    CLS_EXCEEDED = "cls_exceeded"
    TBT_EXCEEDED = "tbt_exceeded"
    LOAD_TIME_EXCEEDED = "load_time_exceeded"
    
    # 错误
    CONSOLE_ERROR = "console_error"
    JS_EXCEPTION = "js_exception"
    NETWORK_ERROR_5XX = "network_error_5xx"
    NETWORK_ERROR_4XX = "network_error_4xx"


@dataclass
class Alert:
    """告警对象"""
    id: Optional[int] = None
    alert_type: str = ""
    severity: str = AlertSeverity.CRITICAL
    title: str = ""
    message: str = ""
    
    # 关联信息
    run_id: Optional[int] = None
    page_result_id: Optional[int] = None
    url: str = ""
    page_name: str = ""
    
    # 详情
    details: Dict[str, Any] = field(default_factory=dict)
    
    # 时间
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    # 状态
    is_new: bool = True  # 是否是新告警（对比历史）


class AlertEngine:
    """告警引擎"""
    
    def __init__(self, thresholds: AlertThresholds):
        self.thresholds = thresholds
        self.alerts: List[Alert] = []
        # 用于去重的缓存 (url + alert_type -> 最近发生时间)
        self._recent_alerts: Dict[str, datetime] = {}
    
    def _should_alert(self, url: str, alert_type: str, deduplicate_hours: int = 24) -> bool:
        """
        检查是否应该告警（去重逻辑）
        
        Args:
            url: 页面 URL
            alert_type: 告警类型
            deduplicate_hours: 去重时间窗口（小时）
        
        Returns:
            True 表示应该告警，False 表示应该抑制
        """
        key = f"{url}:{alert_type}"
        now = datetime.utcnow()
        
        if key in self._recent_alerts:
            last_time = self._recent_alerts[key]
            if now - last_time < timedelta(hours=deduplicate_hours):
                logger.debug(f"⚠️ 告警去重: {key} (上次: {last_time})")
                return False
        
        self._recent_alerts[key] = now
        return True
    
    def _check_availability(self, result: PageResult, page_name: str = "") -> List[Alert]:
        """检查可用性"""
        alerts = []
        
        # HTTP 状态码非 2xx
        if result.http_status and result.http_status >= 400:
            if self._should_alert(result.url, AlertType.SITE_DOWN):
                alerts.append(Alert(
                    alert_type=AlertType.SITE_DOWN,
                    severity=AlertSeverity.CRITICAL,
                    title="页面不可访问",
                    message=f"页面返回 HTTP {result.http_status}",
                    url=result.url,
                    page_name=page_name,
                    page_result_id=result.id,
                    run_id=result.run_id,
                    details={"http_status": result.http_status}
                ))
        
        # 页面状态为 failed 或 timeout
        if result.status in ["failed", "timeout"]:
            if self._should_alert(result.url, AlertType.SITE_DOWN):
                alerts.append(Alert(
                    alert_type=AlertType.SITE_DOWN,
                    severity=AlertSeverity.CRITICAL,
                    title="页面访问失败",
                    message=f"页面巡检状态: {result.status}",
                    url=result.url,
                    page_name=page_name,
                    page_result_id=result.id,
                    run_id=result.run_id,
                    details={"status": result.status}
                ))
        
        return alerts
    
    def _check_performance(self, result: PageResult, page_name: str = "") -> List[Alert]:
        """检查性能指标"""
        alerts = []
        t = self.thresholds
        
        # ========== Lighthouse 得分 ==========
        if result.lh_performance_score is not None:
            score = result.lh_performance_score
            
            # 严重警告
            if score < t.critical_score:
                if self._should_alert(result.url, AlertType.PERFORMANCE_CRITICAL):
                    alerts.append(Alert(
                        alert_type=AlertType.PERFORMANCE_CRITICAL,
                        severity=AlertSeverity.CRITICAL,
                        title="性能得分严重偏低",
                        message=f"Lighthouse Performance 得分: {score}/100 (阈值: {t.critical_score})",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"score": score, "threshold": t.critical_score}
                    ))
            
            # 一般警告
            elif score < t.warning_score:
                if self._should_alert(result.url, AlertType.PERFORMANCE_WARNING):
                    alerts.append(Alert(
                        alert_type=AlertType.PERFORMANCE_WARNING,
                        severity=AlertSeverity.WARNING,
                        title="性能得分偏低",
                        message=f"Lighthouse Performance 得分: {score}/100 (阈值: {t.warning_score})",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"score": score, "threshold": t.warning_score}
                    ))
            
            # 检查得分下降（对比历史）
            if result.id:
                drop_alert = self._check_score_drop(result, page_name)
                if drop_alert:
                    alerts.append(drop_alert)
        
        # ========== Web Vitals ==========
        
        # LCP (最大内容绘制)
        if result.lh_lcp is not None:
            if result.lh_lcp > t.lcp_critical:
                if self._should_alert(result.url, AlertType.LCP_EXCEEDED):
                    alerts.append(Alert(
                        alert_type=AlertType.LCP_EXCEEDED,
                        severity=AlertSeverity.CRITICAL,
                        title="LCP 严重超标",
                        message=f"Largest Contentful Paint: {result.lh_lcp}ms (阈值: {t.lcp_critical}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"lcp": result.lh_lcp, "threshold": t.lcp_critical}
                    ))
            elif result.lh_lcp > t.lcp_warning:
                if self._should_alert(result.url, AlertType.LCP_EXCEEDED, deduplicate_hours=12):
                    alerts.append(Alert(
                        alert_type=AlertType.LCP_EXCEEDED,
                        severity=AlertSeverity.WARNING,
                        title="LCP 超标",
                        message=f"Largest Contentful Paint: {result.lh_lcp}ms (阈值: {t.lcp_warning}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"lcp": result.lh_lcp, "threshold": t.lcp_warning}
                    ))
        
        # CLS (累积布局偏移)
        if result.lh_cls is not None:
            if result.lh_cls > t.cls_critical:
                if self._should_alert(result.url, AlertType.CLS_EXCEEDED):
                    alerts.append(Alert(
                        alert_type=AlertType.CLS_EXCEEDED,
                        severity=AlertSeverity.CRITICAL,
                        title="CLS 严重超标",
                        message=f"Cumulative Layout Shift: {result.lh_cls:.4f} (阈值: {t.cls_critical})",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"cls": result.lh_cls, "threshold": t.cls_critical}
                    ))
            elif result.lh_cls > t.cls_warning:
                if self._should_alert(result.url, AlertType.CLS_EXCEEDED, deduplicate_hours=12):
                    alerts.append(Alert(
                        alert_type=AlertType.CLS_EXCEEDED,
                        severity=AlertSeverity.WARNING,
                        title="CLS 超标",
                        message=f"Cumulative Layout Shift: {result.lh_cls:.4f} (阈值: {t.cls_warning})",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"cls": result.lh_cls, "threshold": t.cls_warning}
                    ))
        
        # TBT (总阻塞时间)
        if result.lh_tbt is not None:
            if result.lh_tbt > t.tbt_critical:
                if self._should_alert(result.url, AlertType.TBT_EXCEEDED):
                    alerts.append(Alert(
                        alert_type=AlertType.TBT_EXCEEDED,
                        severity=AlertSeverity.CRITICAL,
                        title="TBT 严重超标",
                        message=f"Total Blocking Time: {result.lh_tbt}ms (阈值: {t.tbt_critical}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"tbt": result.lh_tbt, "threshold": t.tbt_critical}
                    ))
            elif result.lh_tbt > t.tbt_warning:
                if self._should_alert(result.url, AlertType.TBT_EXCEEDED, deduplicate_hours=12):
                    alerts.append(Alert(
                        alert_type=AlertType.TBT_EXCEEDED,
                        severity=AlertSeverity.WARNING,
                        title="TBT 超标",
                        message=f"Total Blocking Time: {result.lh_tbt}ms (阈值: {t.tbt_warning}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"tbt": result.lh_tbt, "threshold": t.tbt_warning}
                    ))
        
        # ========== 页面加载时间 ==========
        if result.load_time is not None:
            if result.load_time > t.load_time_critical:
                if self._should_alert(result.url, AlertType.LOAD_TIME_EXCEEDED):
                    alerts.append(Alert(
                        alert_type=AlertType.LOAD_TIME_EXCEEDED,
                        severity=AlertSeverity.CRITICAL,
                        title="页面加载时间严重超标",
                        message=f"页面加载时间: {result.load_time}ms (阈值: {t.load_time_critical}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"load_time": result.load_time, "threshold": t.load_time_critical}
                    ))
            elif result.load_time > t.load_time_warning:
                if self._should_alert(result.url, AlertType.LOAD_TIME_EXCEEDED, deduplicate_hours=12):
                    alerts.append(Alert(
                        alert_type=AlertType.LOAD_TIME_EXCEEDED,
                        severity=AlertSeverity.WARNING,
                        title="页面加载时间超标",
                        message=f"页面加载时间: {result.load_time}ms (阈值: {t.load_time_warning}ms)",
                        url=result.url,
                        page_name=page_name,
                        page_result_id=result.id,
                        run_id=result.run_id,
                        details={"load_time": result.load_time, "threshold": t.load_time_warning}
                    ))
        
        return alerts
    
    def _check_score_drop(self, result: PageResult, page_name: str = "") -> Optional[Alert]:
        """检查性能得分下降"""
        if not result.lh_performance_score:
            return None
        
        # 获取历史数据
        history = db.get_page_history(result.url, limit=10)
        if len(history) < 2:
            return None  # 历史数据不足
        
        current_score = result.lh_performance_score
        previous_score = None
        
        # 找最近一次有得分的历史记录
        for record in history[1:]:  # 跳过第一条（当前记录）
            if record.get('lh_performance_score') is not None:
                previous_score = record['lh_performance_score']
                break
        
        if previous_score is None:
            return None
        
        # 单次下降检查
        drop = previous_score - current_score
        if drop >= self.thresholds.score_drop_single:
            return Alert(
                alert_type=AlertType.SCORE_DROP,
                severity=AlertSeverity.WARNING,
                title="性能得分下降",
                message=f"得分从 {previous_score} 下降到 {current_score}，下降了 {drop} 分",
                url=result.url,
                page_name=page_name,
                page_result_id=result.id,
                run_id=result.run_id,
                details={
                    "current_score": current_score,
                    "previous_score": previous_score,
                    "drop": drop
                }
            )
        
        # 连续下降检查
        # 检查最近 N 次是否持续下降
        scores = []
        for record in history:
            s = record.get('lh_performance_score')
            if s is not None:
                scores.append(s)
        
        if len(scores) >= self.thresholds.score_drop_consecutive:
            # 检查是否持续下降
            is_consecutive_drop = True
            for i in range(self.thresholds.score_drop_consecutive - 1):
                if scores[i] >= scores[i + 1]:
                    is_consecutive_drop = False
                    break
            
            if is_consecutive_drop:
                return Alert(
                    alert_type=AlertType.SCORE_DROP,
                    severity=AlertSeverity.WARNING,
                    title="性能得分持续下降",
                    message=f"连续 {self.thresholds.score_drop_consecutive} 次得分下降: {scores[:self.thresholds.score_drop_consecutive]}",
                    url=result.url,
                    page_name=page_name,
                    page_result_id=result.id,
                    run_id=result.run_id,
                    details={"scores": scores[:self.thresholds.score_drop_consecutive]}
                )
        
        return None
    
    def _check_errors(self, result: PageResult, errors: List[ErrorRecord], page_name: str = "") -> List[Alert]:
        """检查错误"""
        alerts = []
        t = self.thresholds
        
        # 按类型分组
        for error in errors:
            # Console Error
            if error.error_type == "console" and error.level == "error":
                if t.alert_on_console_error:
                    # 检查是否是新错误（24小时内没有出现过）
                    is_new = db.is_new_error(error.message, error.error_type, hours=24)
                    
                    if self._should_alert(result.url, AlertType.CONSOLE_ERROR):
                        alerts.append(Alert(
                            alert_type=AlertType.CONSOLE_ERROR,
                            severity=AlertSeverity.WARNING,
                            title="Console 错误",
                            message=error.message[:200] if len(error.message) > 200 else error.message,
                            url=result.url,
                            page_name=page_name,
                            page_result_id=result.id,
                            run_id=result.run_id,
                            is_new=is_new,
                            details={
                                "source": error.source,
                                "line_number": error.line_number,
                                "stack_trace": error.stack_trace
                            }
                        ))
            
            # JS Exception
            elif error.error_type == "exception":
                if t.alert_on_js_exception:
                    is_new = db.is_new_error(error.message, error.error_type, hours=24)
                    
                    if self._should_alert(result.url, AlertType.JS_EXCEPTION):
                        alerts.append(Alert(
                            alert_type=AlertType.JS_EXCEPTION,
                            severity=AlertSeverity.CRITICAL,
                            title="页面异常",
                            message=error.message[:200] if len(error.message) > 200 else error.message,
                            url=result.url,
                            page_name=page_name,
                            page_result_id=result.id,
                            run_id=result.run_id,
                            is_new=is_new,
                            details={"stack_trace": error.stack_trace}
                        ))
            
            # Network Error
            elif error.error_type == "network":
                status = error.http_status or 0
                
                # 5xx 错误
                if status >= 500:
                    if t.alert_on_network_5xx:
                        if self._should_alert(result.url, AlertType.NETWORK_ERROR_5XX):
                            alerts.append(Alert(
                                alert_type=AlertType.NETWORK_ERROR_5XX,
                                severity=AlertSeverity.CRITICAL,
                                title="网络 5xx 错误",
                                message=f"HTTP {status}: {error.url or '未知 URL'}",
                                url=result.url,
                                page_name=page_name,
                                page_result_id=result.id,
                                run_id=result.run_id,
                                details={"http_status": status, "error_url": error.url}
                            ))
                
                # 4xx 错误
                elif status >= 400:
                    if t.alert_on_network_4xx:
                        if self._should_alert(result.url, AlertType.NETWORK_ERROR_4XX, deduplicate_hours=12):
                            alerts.append(Alert(
                                alert_type=AlertType.NETWORK_ERROR_4XX,
                                severity=AlertSeverity.WARNING,
                                title="网络 4xx 错误",
                                message=f"HTTP {status}: {error.url or '未知 URL'}",
                                url=result.url,
                                page_name=page_name,
                                page_result_id=result.id,
                                run_id=result.run_id,
                                details={"http_status": status, "error_url": error.url}
                            ))
        
        return alerts
    
    def analyze_page_result(
        self, 
        result: PageResult, 
        errors: List[ErrorRecord],
        page_name: str = ""
    ) -> List[Alert]:
        """
        分析页面巡检结果，生成告警
        
        Args:
            result: 页面巡检结果
            errors: 错误记录列表
            page_name: 页面名称
        
        Returns:
            告警列表
        """
        all_alerts = []
        
        # 1. 可用性检查
        all_alerts.extend(self._check_availability(result, page_name))
        
        # 2. 性能检查
        all_alerts.extend(self._check_performance(result, page_name))
        
        # 3. 错误检查
        all_alerts.extend(self._check_errors(result, errors, page_name))
        
        self.alerts.extend(all_alerts)
        
        if all_alerts:
            logger.info(f"⚠️  页面 {result.url} 生成 {len(all_alerts)} 个告警")
        
        return all_alerts
    
    def get_alerts(self) -> List[Alert]:
        """获取所有告警"""
        return self.alerts
    
    def get_alerts_by_severity(self, severity: AlertSeverity) -> List[Alert]:
        """按严重程度获取告警"""
        return [a for a in self.alerts if a.severity == severity]
    
    def get_summary(self) -> Dict[str, Any]:
        """获取告警摘要"""
        critical = len(self.get_alerts_by_severity(AlertSeverity.CRITICAL))
        warning = len(self.get_alerts_by_severity(AlertSeverity.WARNING))
        info = len(self.get_alerts_by_severity(AlertSeverity.INFO))
        
        # 按类型统计
        type_counts = {}
        for alert in self.alerts:
            type_counts[alert.alert_type] = type_counts.get(alert.alert_type, 0) + 1
        
        return {
            "total": len(self.alerts),
            "critical": critical,
            "warning": warning,
            "info": info,
            "by_type": type_counts
        }
