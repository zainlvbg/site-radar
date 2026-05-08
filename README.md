# SiteRadar - 网站智能巡检系统

🛡️ 自动化网站巡检工具，定期对目标页面进行性能审计、错误监控、接口健康检查，并生成可视化报告和告警通知。

---

## ✨ 功能特性

| 功能 | 描述 |
|------|------|
| **🌐 浏览器自动化** | 基于 Playwright，完整模拟真实用户行为 |
| **📊 性能审计** | Lighthouse 性能得分、Web Vitals (LCP/FID/CLS/TBT) |
| **❌ 错误监控** | Console 错误、JS 异常、网络请求错误 (4xx/5xx) |
| **📸 截图存档** | 每次巡检自动截图，支持视觉对比 |
| **📈 可视化仪表盘** | 单文件 HTML 仪表盘，直接打开查看历史趋势 |
| **🔔 智能告警** | 飞书群推送，支持告警去重和恢复通知 |
| **⏰ 定时调度** | 集成 Hermes cronjob，支持灵活的调度配置 |
| **🔐 登录态支持** | 支持 Cookie、localStorage、自定义登录脚本 |
| **🎬 业务流程** | 支持多步骤自定义流程巡检（搜索、登录、表单等） |

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装 Python 依赖
pip install playwright pyyaml

# 安装 Playwright 浏览器
playwright install chromium
```

### 2. 配置站点

编辑 `config.yaml`：

```yaml
sites:
  - name: "我的网站"
    base_url: "https://example.com"
    is_active: true
    
    pages:
      - name: "首页"
        url: "https://example.com"
        check_performance: true
        check_errors: true
        capture_screenshot: true
```

### 3. 执行巡检

```bash
# 执行一次完整巡检
python siteradar.py run

# 生成仪表盘
python siteradar.py dashboard

# 查看配置
python siteradar.py config

# 测试单个页面
python siteradar.py test https://example.com
```

### 4. 查看报告

打开生成的仪表盘：
```
open output/dashboard.html
```

---

## 📁 项目结构

```
site-radar/
├── siteradar.py           # 命令行入口
├── config.yaml            # 主配置文件
├── requirements.txt       # Python 依赖
├── README.md             # 本文档
│
├── src/                   # 源代码
│   ├── __init__.py       # 常量和配置
│   ├── config.py         # 配置加载
│   ├── database.py       # SQLite 数据库操作
│   ├── browser.py        # Playwright 浏览器封装
│   ├── checker.py        # 核心巡检逻辑
│   ├── alerts.py         # 告警引擎
│   └── dashboard.py      # HTML 仪表盘生成
│
├── sites/                 # 站点配置目录（可选）
│   └── *.yaml            # 单个站点配置
│
├── data/                  # 数据存储
│   ├── site-radar.db     # SQLite 数据库
│   └── screenshots/      # 截图归档
│       └── YYYY-MM-DD/
│
└── output/                # 输出文件
    └── dashboard.html    # 生成的仪表盘
```

---

## ⚙️ 配置说明

### 完整配置示例

```yaml
# 全局配置
schedule: "0 */2 * * *"    # 每 2 小时
max_concurrent: 3           # 最大并发 3 个页面
page_timeout: 60000         # 页面超时 60 秒

# 告警阈值
thresholds:
  performance:
    critical_score: 50      # 性能得分 < 50: 严重告警
    warning_score: 70       # 性能得分 < 70: 警告
    lcp_critical: 4000      # LCP > 4s: 严重告警
    lcp_warning: 2500       # LCP > 2.5s: 警告
    cls_critical: 0.25      # CLS > 0.25: 严重告警
    cls_warning: 0.1        # CLS > 0.1: 警告
    tbt_critical: 600       # TBT > 600ms: 严重告警
    tbt_warning: 200        # TBT > 200ms: 警告

# 站点配置
sites:
  - name: "生产环境"
    base_url: "https://example.com"
    is_active: true
    
    pages:
      - name: "首页"
        url: "https://example.com"
        check_performance: true
        check_errors: true
        capture_screenshot: true
      
      - name: "商品列表"
        url: "https://example.com/products"
        check_performance: true
        check_errors: true
        
        # 自定义业务流程
        flow:
          steps:
            - type: "click"
              selector: ".filter-btn"
            - type: "wait_for_selector"
              selector: ".filter-panel"
            - type: "screenshot"
              name: "filter-panel"
```

### 登录态配置

```yaml
pages:
  - name: "用户中心"
    url: "https://example.com/user"
    
    # 方式 1: Cookie
    auth:
      cookies:
        - name: "session_id"
          value: "your-session-id"
          domain: ".example.com"
          path: "/"
          httpOnly: true
          secure: true
    
    # 方式 2: localStorage
    auth:
      storage:
        localStorage:
          token: "your-jwt-token"
          user_id: "12345"
    
    # 方式 3: 登录脚本
    auth:
      login_script: |
        // 执行自定义登录逻辑
        document.cookie = 'auth=token123';
        localStorage.setItem('token', 'jwt-token');
```

### 业务流程配置

```yaml
pages:
  - name: "搜索功能"
    url: "https://example.com"
    
    flow:
      steps:
        # 填充搜索框
        - type: "fill"
          selector: "#search-input"
          value: "测试关键词"
        
        # 按回车搜索
        - type: "press"
          key: "Enter"
        
        # 等待结果加载
        - type: "wait_for_selector"
          selector: ".search-results"
          timeout: 10000
        
        # 截图
        - type: "screenshot"
          name: "search-results"
        
        # 点击第一个结果
        - type: "click"
          selector: ".search-results .item:first-child"
        
        # 等待新页面
        - type: "wait"
          duration: 3000
        
        # 截图详情页
        - type: "screenshot"
          name: "detail-page"
```

---

## 📊 告警规则

### 性能告警

| 告警类型 | 触发条件 | 严重程度 |
|---------|---------|---------|
| 性能得分严重 | < 50 分 | 🔴 Critical |
| 性能得分警告 | < 70 分 | 🟡 Warning |
| 得分突降 | 单次下降 > 10 分 | 🟡 Warning |
| 连续下降 | 连续 3 次下降 | 🟡 Warning |
| LCP 严重 | > 4s | 🔴 Critical |
| LCP 警告 | > 2.5s | 🟡 Warning |
| CLS 严重 | > 0.25 | 🔴 Critical |
| CLS 警告 | > 0.1 | 🟡 Warning |
| TBT 严重 | > 600ms | 🔴 Critical |
| TBT 警告 | > 200ms | 🟡 Warning |
| 加载时间 | > 10s | 🔴 Critical |

### 错误告警

| 告警类型 | 触发条件 | 严重程度 |
|---------|---------|---------|
| 页面不可访问 | HTTP >= 400 | 🔴 Critical |
| 页面超时 | 超过 page_timeout | 🔴 Critical |
| Console Error | 任何错误 | 🟡 Warning |
| JS 异常 | 未捕获的异常 | 🔴 Critical |
| 网络 5xx | HTTP 500+ | 🔴 Critical |
| 网络 4xx | HTTP 400+ | 🟡 Warning (默认关闭) |

### 告警去重

同一 URL + 同一告警类型，24 小时内只告警一次。

---

## ⏰ 定时调度

### 使用 Hermes cronjob

```bash
# 创建定时任务（每 2 小时执行一次）
hermes cronjob create \
  --name "site-radar-check" \
  --schedule "0 */2 * * *" \
  --prompt "
执行网站巡检：
1. 运行 python /Users/frontend/site-radar/siteradar.py run --trigger scheduled
2. 运行 python /Users/frontend/site-radar/siteradar.py dashboard
3. 如果有告警，发送到当前飞书群

巡检结果摘要：
- 运行 ID: {run_id}
- 页面数: {total_pages}
- 成功: {completed_pages}
- 失败: {failed_pages}
- 告警数: {alert_count}

仪表盘路径: {dashboard_path}
"
```

### 或使用系统 crontab

```bash
# 编辑 crontab
crontab -e

# 添加任务（每 2 小时执行）
0 */2 * * * cd /path/to/site-radar && python siteradar.py run --trigger scheduled >> /var/log/site-radar.log 2>&1
```

---

## 📈 仪表盘功能

生成的 HTML 仪表盘包含：

### 📊 总览页

- 统计卡片（平均性能得分、LCP、CLS、错误数）
- 性能趋势图（最近 10 次运行）
- Web Vitals 趋势图
- 错误趋势图
- 最近一次巡检详情表

### 📄 页面详情

- 所有监控页面列表
- 性能得分、LCP、CLS、加载时间
- 错误计数、HTTP 状态
- 状态徽章

### ❌ 错误记录

- 最近 24 小时错误列表
- 按类型分类（Console/Network/Exception）
- 错误详情、发生时间、URL

---

## 🔧 命令行参考

```bash
# 执行巡检
python siteradar.py run
python siteradar.py run --trigger scheduled  # 标记为定时触发

# 生成仪表盘
python siteradar.py dashboard

# 查看配置
python siteradar.py config

# 列出运行历史
python siteradar.py list
python siteradar.py list -n 20  # 显示 20 条

# 查看运行详情
python siteradar.py show 1  # 查看运行 #1

# 测试单个页面
python siteradar.py test https://example.com
```

---

## 📋 数据库表结构

| 表名 | 说明 |
|------|------|
| `runs` | 巡检运行记录 |
| `page_results` | 页面巡检结果 |
| `errors` | 错误记录 |

---

## 🔄 开发计划

### v1.0 (当前版本)
- ✅ 基础巡检功能
- ✅ Playwright 浏览器自动化
- ✅ Console/Network/Exception 错误捕获
- ✅ 截图存档
- ✅ SQLite 数据存储
- ✅ HTML 仪表盘
- ✅ YAML 配置
- ✅ 命令行工具

### v1.1 (计划中)
- ⏳ Lighthouse 性能审计集成
- ⏳ 告警引擎（飞书推送）
- ⏳ 告警去重机制
- ⏳ 历史数据清理
- ⏳ 性能趋势对比

### v1.2 (计划中)
- ⏳ 登录态支持（Cookie/Storage/脚本）
- ⏳ 自定义业务流程
- ⏳ 截图对比（视觉变化检测）
- ⏳ 多环境支持（测试/预发布/生产）

### v2.0 (计划中)
- ⏳ Prometheus + Grafana 集成
- ⏳ Web UI 管理界面
- ⏳ 多渠道告警（邮件/钉钉/Webhook）
- ⏳ 分布式部署支持

---

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 许可证

MIT License

---

## 🔗 相关链接

- [Playwright 文档](https://playwright.dev/python/)
- [Lighthouse 文档](https://developer.chrome.com/docs/lighthouse/overview/)
- [Web Vitals 指南](https://web.dev/vitals/)
