"""
HTML 仪表盘生成器
"""

from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import json
import logging

from src import OUTPUT_DIR
from src.database import db, PageResult, ErrorRecord
from src.alerts import AlertSeverity

logger = logging.getLogger("site-radar.dashboard")


class DashboardGenerator:
    """HTML 仪表盘生成器"""
    
    def __init__(self):
        self.output_dir = OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate(self) -> str:
        """生成完整的 HTML 仪表盘"""
        logger.info("📊 生成仪表盘...")
        
        # 获取数据
        data = self._collect_data()
        
        # 生成 HTML
        html = self._render_html(data)
        
        # 保存文件
        output_path = self.output_dir / "dashboard.html"
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)
        
        logger.info(f"✅ 仪表盘已生成: {output_path}")
        return str(output_path)
    
    def _collect_data(self) -> Dict[str, Any]:
        """收集仪表盘数据"""
        # 最近的运行记录
        latest_runs = db.get_latest_runs(limit=50)
        
        if not latest_runs:
            return {
                "summary": {
                    "total_runs": 0,
                    "total_pages": 0,
                    "total_errors": 0,
                    "last_run": None
                },
                "runs": [],
                "urls": [],
                "errors": [],
                "trend_data": []
            }
        
        # 获取最近一次运行的详情
        latest_run = latest_runs[0]
        latest_run_id = latest_run['id']
        
        # 获取该运行的所有页面结果
        page_results = db.get_page_results(latest_run_id)
        
        # 获取最近 24 小时的错误
        recent_errors = db.get_recent_errors(hours=24)
        
        # 获取所有有历史记录的 URL
        all_urls = db.get_urls_with_history()
        
        # 收集趋势数据（最近 10 次运行）
        trend_data = self._collect_trend_data(latest_runs[:10])
        
        # 计算统计
        summary = {
            "total_runs": len(latest_runs),
            "total_pages": len(page_results),
            "total_errors": len(recent_errors),
            "last_run": latest_run['started_at'],
            "success_pages": sum(1 for r in page_results if r['status'] == 'success'),
            "failed_pages": sum(1 for r in page_results if r['status'] != 'success'),
            "avg_performance_score": self._calc_avg_score(page_results, 'lh_performance_score'),
            "avg_lcp": self._calc_avg_score(page_results, 'lh_lcp'),
            "avg_cls": self._calc_avg_score(page_results, 'lh_cls'),
        }
        
        # 页面详情
        pages_detail = []
        for result in page_results:
            # 获取该页面的历史趋势
            history = db.get_page_history(result['url'], limit=10)
            
            pages_detail.append({
                "result": result,
                "history": history,
                "score_history": [r.get('lh_performance_score') for r in history if r.get('lh_performance_score') is not None],
                "lcp_history": [r.get('lh_lcp') for r in history if r.get('lh_lcp') is not None],
            })
        
        return {
            "summary": summary,
            "latest_run": latest_run,
            "page_results": page_results,
            "pages_detail": pages_detail,
            "recent_errors": recent_errors,
            "all_urls": all_urls,
            "trend_data": trend_data,
        }
    
    def _collect_trend_data(self, runs: List[Dict]) -> Dict[str, Any]:
        """收集趋势数据"""
        trend = {
            "labels": [],
            "avg_performance": [],
            "avg_lcp": [],
            "avg_cls": [],
            "error_count": [],
            "page_count": [],
        }
        
        for run in reversed(runs):  # 从旧到新
            run_id = run['id']
            started_at = run['started_at']
            
            # 格式化时间标签
            try:
                dt = datetime.fromisoformat(started_at)
                label = dt.strftime("%m-%d %H:%M")
            except:
                label = started_at[:16]
            
            trend['labels'].append(label)
            
            # 获取该运行的页面结果
            page_results = db.get_page_results(run_id)
            
            if page_results:
                # 平均性能得分
                scores = [r['lh_performance_score'] for r in page_results if r['lh_performance_score'] is not None]
                trend['avg_performance'].append(round(sum(scores) / len(scores), 1) if scores else None)
                
                # 平均 LCP
                lcps = [r['lh_lcp'] for r in page_results if r['lh_lcp'] is not None]
                trend['avg_lcp'].append(round(sum(lcps) / len(lcps), 0) if lcps else None)
                
                # 平均 CLS
                clss = [r['lh_cls'] for r in page_results if r['lh_cls'] is not None]
                trend['avg_cls'].append(round(sum(clss) / len(clss), 4) if clss else None)
                
                # 页面数
                trend['page_count'].append(len(page_results))
                
                # 错误数（从数据库查询）
                errors = db.get_run_errors(run_id)
                trend['error_count'].append(len(errors))
            else:
                trend['avg_performance'].append(None)
                trend['avg_lcp'].append(None)
                trend['avg_cls'].append(None)
                trend['page_count'].append(0)
                trend['error_count'].append(0)
        
        return trend
    
    def _calc_avg_score(self, results: List[Dict], key: str) -> Optional[float]:
        """计算平均得分"""
        values = [r[key] for r in results if r.get(key) is not None]
        if not values:
            return None
        return round(sum(values) / len(values), 1)
    
    def _render_html(self, data: Dict[str, Any]) -> str:
        """渲染 HTML"""
        # 将数据转为 JSON 供前端使用
        json_data = json.dumps(data, ensure_ascii=False, default=str)
        
        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>SiteRadar - 网站巡检仪表盘</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e7;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 20px;
        }}
        
        /* Header */
        .header {{
            background: rgba(30, 41, 59, 0.8);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(99, 102, 241, 0.2);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
        }}
        
        .header h1 {{
            font-size: 28px;
            font-weight: 700;
            background: linear-gradient(90deg, #818cf8, #a78bfa);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 8px;
        }}
        
        .header .meta {{
            color: #94a3b8;
            font-size: 14px;
        }}
        
        .header .meta span {{
            margin-right: 24px;
        }}
        
        /* Stats Grid */
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 16px;
            margin-bottom: 24px;
        }}
        
        .stat-card {{
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 12px;
            padding: 20px;
            transition: transform 0.2s, border-color 0.2s;
        }}
        
        .stat-card:hover {{
            transform: translateY(-2px);
            border-color: rgba(99, 102, 241, 0.4);
        }}
        
        .stat-card .label {{
            color: #94a3b8;
            font-size: 13px;
            margin-bottom: 8px;
        }}
        
        .stat-card .value {{
            font-size: 28px;
            font-weight: 700;
        }}
        
        .stat-card .value.good {{ color: #4ade80; }}
        .stat-card .value.warning {{ color: #fbbf24; }}
        .stat-card .value.danger {{ color: #f87171; }}
        .stat-card .value.info {{ color: #60a5fa; }}
        
        .stat-card .change {{
            font-size: 12px;
            margin-top: 4px;
        }}
        
        /* Charts */
        .charts-section {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 20px;
            margin-bottom: 24px;
        }}
        
        .chart-card {{
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 12px;
            padding: 20px;
        }}
        
        .chart-card h3 {{
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 16px;
            color: #e4e4e7;
        }}
        
        .chart-container {{
            position: relative;
            height: 250px;
        }}
        
        /* Page Table */
        .section-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 16px;
        }}
        
        .section-header h2 {{
            font-size: 18px;
            font-weight: 600;
            color: #e4e4e7;
        }}
        
        .table-container {{
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 12px;
            overflow: hidden;
            margin-bottom: 24px;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
        th {{
            background: rgba(99, 102, 241, 0.1);
            text-align: left;
            padding: 14px 16px;
            font-weight: 600;
            color: #a5b4fc;
            font-size: 13px;
            border-bottom: 1px solid rgba(99, 102, 241, 0.15);
        }}
        
        td {{
            padding: 14px 16px;
            border-bottom: 1px solid rgba(99, 102, 241, 0.08);
            font-size: 14px;
        }}
        
        tr:hover {{
            background: rgba(99, 102, 241, 0.05);
        }}
        
        /* Status Badges */
        .badge {{
            display: inline-flex;
            align-items: center;
            padding: 4px 10px;
            border-radius: 9999px;
            font-size: 12px;
            font-weight: 500;
        }}
        
        .badge-success {{
            background: rgba(74, 222, 128, 0.15);
            color: #4ade80;
        }}
        
        .badge-warning {{
            background: rgba(251, 191, 36, 0.15);
            color: #fbbf24;
        }}
        
        .badge-danger {{
            background: rgba(248, 113, 113, 0.15);
            color: #f87171;
        }}
        
        .badge-info {{
            background: rgba(96, 165, 250, 0.15);
            color: #60a5fa;
        }}
        
        /* Score Colors */
        .score-excellent {{ color: #4ade80; }}  /* >= 90 */
        .score-good {{ color: #86efac; }}       /* >= 80 */
        .score-moderate {{ color: #fbbf24; }}   /* >= 50 */
        .score-poor {{ color: #f87171; }}        /* < 50 */
        
        /* Errors Section */
        .errors-section {{
            margin-bottom: 24px;
        }}
        
        .error-item {{
            background: rgba(248, 113, 113, 0.08);
            border-left: 3px solid #f87171;
            border-radius: 0 8px 8px 0;
            padding: 16px;
            margin-bottom: 12px;
        }}
        
        .error-item.warning {{
            background: rgba(251, 191, 36, 0.08);
            border-left-color: #fbbf24;
        }}
        
        .error-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        
        .error-type {{
            font-weight: 600;
            font-size: 13px;
        }}
        
        .error-time {{
            font-size: 12px;
            color: #94a3b8;
        }}
        
        .error-message {{
            font-family: 'JetBrains Mono', 'Fira Code', monospace;
            font-size: 13px;
            color: #fecaca;
            word-break: break-all;
        }}
        
        .error-url {{
            font-size: 12px;
            color: #94a3b8;
            margin-top: 8px;
        }}
        
        /* Empty State */
        .empty-state {{
            text-align: center;
            padding: 40px;
            color: #64748b;
        }}
        
        .empty-state svg {{
            width: 48px;
            height: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }}
        
        /* Tabs */
        .tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 16px;
        }}
        
        .tab {{
            padding: 8px 16px;
            background: rgba(30, 41, 59, 0.8);
            border: 1px solid rgba(99, 102, 241, 0.15);
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.2s;
        }}
        
        .tab:hover {{
            border-color: rgba(99, 102, 241, 0.4);
        }}
        
        .tab.active {{
            background: rgba(99, 102, 241, 0.2);
            border-color: rgba(99, 102, 241, 0.5);
            color: #a5b4fc;
        }}
        
        .tab-content {{
            display: none;
        }}
        
        .tab-content.active {{
            display: block;
        }}
        
        /* Footer */
        .footer {{
            text-align: center;
            padding: 24px;
            color: #64748b;
            font-size: 13px;
        }}
        
        .footer a {{
            color: #818cf8;
            text-decoration: none;
        }}
        
        /* Responsive */
        @media (max-width: 768px) {{
            .stats-grid {{
                grid-template-columns: repeat(2, 1fr);
            }}
            
            .charts-section {{
                grid-template-columns: 1fr;
            }}
            
            .header h1 {{
                font-size: 22px;
            }}
            
            table {{
                font-size: 12px;
            }}
            
            th, td {{
                padding: 10px 12px;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Header -->
        <div class="header">
            <h1>🛡️ SiteRadar 网站巡检仪表盘</h1>
            <div class="meta">
                <span>📊 总计运行: <strong id="total-runs">0</strong> 次</span>
                <span>📄 监控页面: <strong id="total-pages">0</strong> 个</span>
                <span>⏰ 最后更新: <strong id="last-update">-</strong></span>
            </div>
        </div>
        
        <!-- Stats Grid -->
        <div class="stats-grid">
            <div class="stat-card">
                <div class="label">🚀 平均性能得分</div>
                <div class="value" id="avg-score">-</div>
                <div class="change">Performance (0-100)</div>
            </div>
            <div class="stat-card">
                <div class="label">⏱️ 平均 LCP</div>
                <div class="value" id="avg-lcp">-</div>
                <div class="change">Largest Contentful Paint</div>
            </div>
            <div class="stat-card">
                <div class="label">📐 平均 CLS</div>
                <div class="value" id="avg-cls">-</div>
                <div class="change">Cumulative Layout Shift</div>
            </div>
            <div class="stat-card">
                <div class="label">❌ 最近 24h 错误</div>
                <div class="value danger" id="error-count">0</div>
                <div class="change">Console + Network + Exceptions</div>
            </div>
        </div>
        
        <!-- Tabs -->
        <div class="tabs">
            <div class="tab active" data-tab="overview">📈 总览</div>
            <div class="tab" data-tab="pages">📄 页面详情</div>
            <div class="tab" data-tab="errors">❌ 错误记录</div>
        </div>
        
        <!-- Overview Tab -->
        <div class="tab-content active" id="tab-overview">
            <!-- Charts -->
            <div class="charts-section">
                <div class="chart-card">
                    <h3>📊 性能趋势</h3>
                    <div class="chart-container">
                        <canvas id="performanceChart"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <h3>⏱️ Web Vitals 趋势</h3>
                    <div class="chart-container">
                        <canvas id="vitalsChart"></canvas>
                    </div>
                </div>
                <div class="chart-card">
                    <h3>❌ 错误趋势</h3>
                    <div class="chart-container">
                        <canvas id="errorsChart"></canvas>
                    </div>
                </div>
            </div>
            
            <!-- Recent Run Summary -->
            <div class="section-header">
                <h2>📋 最近一次巡检</h2>
            </div>
            <div class="table-container" id="recent-run-table">
                <!-- 动态填充 -->
            </div>
        </div>
        
        <!-- Pages Tab -->
        <div class="tab-content" id="tab-pages">
            <div class="section-header">
                <h2>📄 页面详情</h2>
            </div>
            <div class="table-container" id="pages-table">
                <!-- 动态填充 -->
            </div>
        </div>
        
        <!-- Errors Tab -->
        <div class="tab-content" id="tab-errors">
            <div class="section-header">
                <h2>❌ 最近 24 小时错误</h2>
            </div>
            <div class="errors-section" id="errors-list">
                <!-- 动态填充 -->
            </div>
        </div>
        
        <!-- Footer -->
        <div class="footer">
            <p>🛡️ SiteRadar 网站巡检系统 | 数据每 2 小时自动更新</p>
        </div>
    </div>
    
    <script>
        // 数据
        const data = {json_data};
        
        // 工具函数
        function getScoreClass(score) {{
            if (score === null || score === undefined) return '';
            if (score >= 90) return 'score-excellent';
            if (score >= 80) return 'score-good';
            if (score >= 50) return 'score-moderate';
            return 'score-poor';
        }}
        
        function getStatusBadge(status) {{
            switch(status) {{
                case 'success': return '<span class="badge badge-success">✓ 成功</span>';
                case 'timeout': return '<span class="badge badge-warning">⏰ 超时</span>';
                case 'failed': return '<span class="badge badge-danger">✗ 失败</span>';
                default: return '<span class="badge badge-info">' + status + '</span>';
            }}
        }}
        
        function formatTime(isoStr) {{
            if (!isoStr) return '-';
            try {{
                const dt = new Date(isoStr);
                return dt.toLocaleString('zh-CN');
            }} catch {{
                return isoStr;
            }}
        }}
        
        function formatDuration(ms) {{
            if (ms === null || ms === undefined) return '-';
            if (ms >= 1000) {{
                return (ms / 1000).toFixed(2) + 's';
            }}
            return ms + 'ms';
        }}
        
        // 填充头部信息
        function fillHeader() {{
            const summary = data.summary;
            document.getElementById('total-runs').textContent = summary.total_runs;
            document.getElementById('total-pages').textContent = summary.total_pages;
            document.getElementById('last-update').textContent = formatTime(summary.last_run);
            
            // 平均得分
            const avgScore = summary.avg_performance_score;
            const scoreEl = document.getElementById('avg-score');
            if (avgScore !== null) {{
                scoreEl.textContent = avgScore;
                scoreEl.className = 'value ' + getScoreClass(avgScore);
            }} else {{
                scoreEl.textContent = '-';
            }}
            
            // 平均 LCP
            const avgLcp = summary.avg_lcp;
            document.getElementById('avg-lcp').textContent = avgLcp ? formatDuration(avgLcp) : '-';
            
            // 平均 CLS
            const avgCls = summary.avg_cls;
            document.getElementById('avg-cls').textContent = avgCls !== null ? avgCls.toFixed(4) : '-';
            
            // 错误数
            document.getElementById('error-count').textContent = summary.total_errors;
        }}
        
        // 填充最近运行表格
        function fillRecentRunTable() {{
            const results = data.page_results;
            const container = document.getElementById('recent-run-table');
            
            if (!results || results.length === 0) {{
                container.innerHTML = '<div class="empty-state"><p>暂无数据</p></div>';
                return;
            }}
            
            let html = '<table><thead><tr>';
            html += '<th>状态</th>';
            html += '<th>页面</th>';
            html += '<th>性能得分</th>';
            html += '<th>LCP</th>';
            html += '<th>CLS</th>';
            html += '<th>加载时间</th>';
            html += '<th>错误</th>';
            html += '<th>HTTP</th>';
            html += '</tr></thead><tbody>';
            
            for (const r of results) {{
                html += '<tr>';
                html += '<td>' + getStatusBadge(r.status) + '</td>';
                
                // URL
                const displayUrl = r.url.length > 60 ? r.url.substring(0, 60) + '...' : r.url;
                html += '<td><a href="' + r.url + '" target="_blank" style="color:#a5b4fc;text-decoration:none;">' + displayUrl + '</a></td>';
                
                // 性能得分
                const score = r.lh_performance_score;
                if (score !== null) {{
                    html += '<td class="' + getScoreClass(score) + '"><strong>' + score + '</strong></td>';
                }} else {{
                    html += '<td>-</td>';
                }}
                
                // LCP
                html += '<td>' + (r.lh_lcp ? formatDuration(r.lh_lcp) : '-') + '</td>';
                
                // CLS
                html += '<td>' + (r.lh_cls !== null ? r.lh_cls.toFixed(4) : '-') + '</td>';
                
                // 加载时间
                html += '<td>' + (r.load_time ? formatDuration(r.load_time) : '-') + '</td>';
                
                // 错误数
                const errorTotal = (r.error_count || 0) + (r.request_error_count || 0);
                if (errorTotal > 0) {{
                    html += '<td><span class="badge badge-danger">' + errorTotal + '</span></td>';
                }} else {{
                    html += '<td><span class="badge badge-success">0</span></td>';
                }}
                
                // HTTP 状态
                if (r.http_status) {{
                    if (r.http_status >= 400) {{
                        html += '<td><span class="badge badge-danger">' + r.http_status + '</span></td>';
                    }} else {{
                        html += '<td><span class="badge badge-success">' + r.http_status + '</span></td>';
                    }}
                }} else {{
                    html += '<td>-</td>';
                }}
                
                html += '</tr>';
            }}
            
            html += '</tbody></table>';
            container.innerHTML = html;
        }}
        
        // 填充错误列表
        function fillErrorsList() {{
            const errors = data.recent_errors;
            const container = document.getElementById('errors-list');
            
            if (!errors || errors.length === 0) {{
                container.innerHTML = '<div class="empty-state"><p>✅ 最近 24 小时没有错误</p></div>';
                return;
            }}
            
            let html = '';
            for (const err of errors) {{
                const isWarning = err.level === 'warning' || (err.http_status && err.http_status < 500);
                const cssClass = isWarning ? 'error-item warning' : 'error-item';
                
                html += '<div class="' + cssClass + '">';
                html += '<div class="error-header">';
                
                // 错误类型
                let typeLabel = err.error_type;
                if (err.error_type === 'console') typeLabel = 'Console ' + err.level;
                else if (err.error_type === 'exception') typeLabel = '页面异常';
                else if (err.error_type === 'network') typeLabel = '网络错误 ' + (err.http_status || '');
                
                html += '<span class="error-type">' + typeLabel + '</span>';
                html += '<span class="error-time">' + formatTime(err.occurred_at) + '</span>';
                html += '</div>';
                
                // 错误消息
                html += '<div class="error-message">' + (err.message || '-') + '</div>';
                
                // URL
                if (err.url) {{
                    html += '<div class="error-url">📍 ' + err.url + '</div>';
                }}
                if (err.source) {{
                    html += '<div class="error-url">📁 ' + err.source;
                    if (err.line_number) html += ':' + err.line_number;
                    html += '</div>';
                }}
                
                html += '</div>';
            }}
            
            container.innerHTML = html;
        }}
        
        // 绘制图表
        function createCharts() {{
            const trend = data.trend_data;
            if (!trend || !trend.labels || trend.labels.length === 0) {{
                console.log('No trend data available');
                return;
            }}
            
            const chartColors = {{
                performance: 'rgb(129, 140, 248)',
                lcp: 'rgb(74, 222, 128)',
                cls: 'rgb(251, 191, 36)',
                errors: 'rgb(248, 113, 113)',
                grid: 'rgba(99, 102, 241, 0.1)'
            }};
            
            // 性能趋势图
            const perfCtx = document.getElementById('performanceChart').getContext('2d');
            new Chart(perfCtx, {{
                type: 'line',
                data: {{
                    labels: trend.labels,
                    datasets: [{{
                        label: '性能得分',
                        data: trend.avg_performance,
                        borderColor: chartColors.performance,
                        backgroundColor: 'rgba(129, 140, 248, 0.1)',
                        fill: true,
                        tension: 0.4
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: true, labels: {{ color: '#94a3b8' }} }},
                    }},
                    scales: {{
                        y: {{
                            min: 0, max: 100,
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }},
                        x: {{
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }}
                    }}
                }}
            }});
            
            // Web Vitals 图
            const vitalsCtx = document.getElementById('vitalsChart').getContext('2d');
            new Chart(vitalsCtx, {{
                type: 'line',
                data: {{
                    labels: trend.labels,
                    datasets: [
                        {{
                            label: 'LCP (ms)',
                            data: trend.avg_lcp,
                            borderColor: chartColors.lcp,
                            yAxisID: 'y',
                            tension: 0.4
                        }},
                        {{
                            label: 'CLS',
                            data: trend.avg_cls,
                            borderColor: chartColors.cls,
                            yAxisID: 'y1',
                            tension: 0.4
                        }}
                    ]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: true, labels: {{ color: '#94a3b8' }} }},
                    }},
                    scales: {{
                        y: {{
                            type: 'linear',
                            position: 'left',
                            title: {{ display: true, text: 'LCP (ms)', color: '#94a3b8' }},
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }},
                        y1: {{
                            type: 'linear',
                            position: 'right',
                            title: {{ display: true, text: 'CLS', color: '#94a3b8' }},
                            grid: {{ display: false }},
                            ticks: {{ color: '#94a3b8' }}
                        }},
                        x: {{
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }}
                    }}
                }}
            }});
            
            // 错误趋势图
            const errorsCtx = document.getElementById('errorsChart').getContext('2d');
            new Chart(errorsCtx, {{
                type: 'bar',
                data: {{
                    labels: trend.labels,
                    datasets: [{{
                        label: '错误数',
                        data: trend.error_count,
                        backgroundColor: 'rgba(248, 113, 113, 0.6)',
                        borderColor: chartColors.errors,
                        borderWidth: 1
                    }}]
                }},
                options: {{
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {{
                        legend: {{ display: false }},
                    }},
                    scales: {{
                        y: {{
                            beginAtZero: true,
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }},
                        x: {{
                            grid: {{ color: chartColors.grid }},
                            ticks: {{ color: '#94a3b8' }}
                        }}
                    }}
                }}
            }});
        }}
        
        // Tab 切换
        function setupTabs() {{
            const tabs = document.querySelectorAll('.tab');
            tabs.forEach(tab => {{
                tab.addEventListener('click', () => {{
                    // 移除所有 active
                    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
                    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
                    
                    // 添加当前 active
                    tab.classList.add('active');
                    const tabName = tab.dataset.tab;
                    document.getElementById('tab-' + tabName).classList.add('active');
                }});
            }});
        }}
        
        // 初始化
        function init() {{
            fillHeader();
            fillRecentRunTable();
            fillErrorsList();
            createCharts();
            setupTabs();
        }}
        
        // 页面加载完成后执行
        if (document.readyState === 'loading') {{
            document.addEventListener('DOMContentLoaded', init);
        }} else {{
            init();
        }}
    </script>
</body>
</html>
'''
