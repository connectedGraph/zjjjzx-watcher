from __future__ import annotations

from dataclasses import dataclass
from zjjjzx.core.parser import Listing


@dataclass(frozen=True)
class Profile:
    areas: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()
    grades: tuple[str, ...] = ()
    min_price: float | None = None
    max_price: float | None = None
    max_distance_meters: float | None = None
    allow_online: bool = True
    conditions: str = ""
    user_gender: str = ""


def hard_filter(listing: Listing, profile: Profile, distance_meters: float | None = None) -> tuple[bool, str]:
    if not profile.allow_online and "线上" in listing.teaching_mode:
        return False, "不接受线上"
    if profile.max_distance_meters is not None and distance_meters is None:
        return False, "无法测得距离"
    if profile.max_distance_meters is not None and distance_meters > profile.max_distance_meters:
        return False, "距离超出范围"
    return True, ""


def deterministic_score(
    extracted: dict,
    distance_meters: float | None,
    max_distance_meters: float,
) -> float:
    rate = extracted.get("hourly_rate_max")
    if not isinstance(rate, (int, float)):
        rate = extracted.get("hourly_rate_min")
    if not isinstance(rate, (int, float)):
        rate = 0
    grade_rank = extracted.get("grade_rank", 0)
    if not isinstance(grade_rank, (int, float)):
        grade_rank = 0
    distance_score = 0
    if distance_meters is not None and max_distance_meters > 0:
        distance_score = max(0, 15 * (1 - distance_meters / max_distance_meters))
    price_score = min(60, max(0, float(rate) / 500 * 60))
    grade_score = min(25, max(0, float(grade_rank) / 10 * 25))
    return round(price_score + grade_score + distance_score, 2)


def sort_key(extracted: dict, distance_meters: float | None) -> tuple[float, float, float]:
    rate = extracted.get("hourly_rate_max")
    if not isinstance(rate, (int, float)):
        rate = extracted.get("hourly_rate_min")
    if not isinstance(rate, (int, float)):
        rate = 0
    grade_rank = extracted.get("grade_rank", 0)
    if not isinstance(grade_rank, (int, float)):
        grade_rank = 0
    return (-float(rate), -float(grade_rank), distance_meters if distance_meters is not None else float("inf"))
