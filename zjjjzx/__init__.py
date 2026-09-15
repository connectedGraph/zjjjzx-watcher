"""zjjjzx-watcher: 智能家教需求抓取、测距与语义匹配系统"""

__version__ = "0.2.0"

from zjjjzx.config import load_config, load_dotenv, make_profile
from zjjjzx.core.baidu_maps import BaiduMapsClient, BaiduMapsError, Coordinate, Route
from zjjjzx.core.engine import run_pipeline
from zjjjzx.core.fetcher import fetch_html
from zjjjzx.core.filters import Profile, deterministic_score, hard_filter, sort_key
from zjjjzx.core.llm_client import evaluate
from zjjjzx.core.parser import Listing, parse_listings
from zjjjzx.core.report import write_report
from zjjjzx.core.store import Store

__all__ = [
    "__version__",
    "load_config",
    "load_dotenv",
    "make_profile",
    "BaiduMapsClient",
    "BaiduMapsError",
    "Coordinate",
    "Route",
    "run_pipeline",
    "fetch_html",
    "Profile",
    "deterministic_score",
    "hard_filter",
    "sort_key",
    "evaluate",
    "Listing",
    "parse_listings",
    "write_report",
    "Store",
]
