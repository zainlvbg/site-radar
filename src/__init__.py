# SiteRadar - 网站智能巡检系统

import logging
import os
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 数据目录
DATA_DIR = PROJECT_ROOT / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
OUTPUT_DIR = PROJECT_ROOT / "output"
SITES_DIR = PROJECT_ROOT / "sites"

# 确保目录存在
for d in [DATA_DIR, SCREENSHOTS_DIR, OUTPUT_DIR, SITES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# 数据库路径
DB_PATH = DATA_DIR / "site-radar.db"

# 配置文件路径
CONFIG_PATH = PROJECT_ROOT / "config.yaml"

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("site-radar")

# 默认告警阈值
DEFAULT_THRESHOLDS = {
    # 性能告警
    "performance": {
        "critical_score": 50,  # < 50 分：红色告警
        "warning_score": 70,   # < 70 分：黄色警告
        "score_drop_single": 10,  # 单次下降 > 10 分
        "score_drop_consecutive": 3,  # 连续下降 3 次
        "lcp_critical": 4000,  # ms
        "lcp_warning": 2500,   # ms
        "cls_critical": 0.25,
        "cls_warning": 0.1,
        "tbt_critical": 600,   # ms
        "tbt_warning": 200,    # ms
        "load_time_warning": 5000,  # ms
        "load_time_critical": 10000,  # ms
    },
    # 错误告警
    "errors": {
        "alert_on_console_error": True,
        "alert_on_js_exception": True,
        "alert_on_network_5xx": True,
        "alert_on_network_4xx": False,  # 4xx 默认关闭
    }
}
