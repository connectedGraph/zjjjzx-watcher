from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from collections import Counter
from typing import Any
from urllib.error import HTTPError, URLError

from zjjjzx.core.parser import Listing


DEFAULT_EMBEDDING_THRESHOLD = 0.08


def _tokenize_chinese(text: str) -> Counter:
    chars = [c for c in text if not c.isspace()]
    bigrams = ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]
    words = re.findall(r"[\u4e00-\u9fa5]{2,4}|[a-zA-Z0-9]+", text)
    return Counter(words + bigrams)


def _cosine_similarity(v1: Counter, v2: Counter) -> float:
    intersection = set(v1.keys()) & set(v2.keys())
    if not intersection:
        return 0.0
    numerator = sum(v1[x] * v2[x] for x in intersection)
    sum1 = sum(v1[x] ** 2 for x in v1.keys())
    sum2 = sum(v2[x] ** 2 for x in v2.keys())
    denominator = math.sqrt(sum1) * math.sqrt(sum2)
    return (numerator / denominator) if denominator else 0.0


def _extract_fields_from_listing(listing: Listing) -> dict[str, Any]:
    grade_rank = 0
    grade_text = listing.grade
    if any(g in grade_text for g in ("1年级", "一年级", "一", "1")):
        grade_rank = 1
    elif any(g in grade_text for g in ("2年级", "二年级", "二", "2")):
        grade_rank = 2
    elif any(g in grade_text for g in ("3年级", "三年级", "三", "3")):
        grade_rank = 3
    elif any(g in grade_text for g in ("4年级", "四年级", "四", "4")):
        grade_rank = 4
    elif any(g in grade_text for g in ("5年级", "五年级", "五", "5")):
        grade_rank = 5
    elif any(g in grade_text for g in ("6年级", "六年级", "六", "6")):
        grade_rank = 6
    elif any(g in grade_text for g in ("初一", "七年级", "7年级")):
        grade_rank = 7
    elif any(g in grade_text for g in ("初二", "八年级", "8年级")):
        grade_rank = 8
    elif any(g in grade_text for g in ("初三", "九年级", "9年级")):
        grade_rank = 9
    elif any(g in grade_text for g in ("高一", "高1")):
        grade_rank = 10
    elif any(g in grade_text for g in ("高二", "高2")):
        grade_rank = 11
    elif any(g in grade_text for g in ("高三", "高3")):
        grade_rank = 12

    hourly_min = None
    hourly_max = None
    price_val = listing.price_value
    price_txt = listing.price_text

    # Parse hourly rates like '140元/次，2h' -> 70
    match_hour = re.search(r"(\d+(?:\.\d+)?)\s*元(?:/|每)小时", price_txt)
    match_session = re.search(r"(\d+(?:\.\d+)?)\s*元(?:/|每)次[，,]\s*(\d+(?:\.\d+)?)\s*h", price_txt)
    if match_hour:
        hourly_min = hourly_max = float(match_hour.group(1))
    elif match_session:
        session_price = float(match_session.group(1))
        hours = float(match_session.group(2))
        if hours > 0:
            hourly_min = hourly_max = round(session_price / hours, 1)
    elif price_val:
        hourly_min = hourly_max = float(price_val)

    return {
        "subject": listing.subject,
        "grade": listing.grade,
        "grade_rank": grade_rank,
        "student_gender": listing.gender,
        "hourly_rate_min": hourly_min,
        "hourly_rate_max": hourly_max,
        "total_income": None,
        "schedule_text": listing.teaching_time,
        "mode": listing.teaching_mode,
    }


class EmbeddingMatcher:
    def __init__(
        self,
        api_url: str = "",
        api_key: str = "",
        model: str = "text-embedding-3-small",
        threshold: float = DEFAULT_EMBEDDING_THRESHOLD,
    ) -> None:
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.threshold = threshold

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> EmbeddingMatcher:
        emb_cfg = config.get("embedding", {})
        api_url = emb_cfg.get("url", os.getenv("EMBEDDING_API_URL", ""))
        api_key = emb_cfg.get("api_key", os.getenv("EMBEDDING_API_KEY", ""))
        model = emb_cfg.get("model", "text-embedding-3-small")
        threshold = float(emb_cfg.get("threshold", DEFAULT_EMBEDDING_THRESHOLD))
        return cls(api_url=api_url, api_key=api_key, model=model, threshold=threshold)

    def evaluate_listing(self, conditions: str, listing: Listing) -> dict[str, Any]:
        text = f"{listing.title} {listing.subject} {listing.grade} {listing.requirements} {listing.address}"

        # 1. Negative hard exclusions
        req = listing.requirements
        gender_req = listing.gender
        title = listing.title
        subject = listing.subject

        if gender_req == "女" or "女老师" in req or "女教" in req or "限女" in req:
            return {
                "pass": False,
                "reason": "家教要求女教师，与用户性别不匹配",
                "score": 0.0,
                "extracted": _extract_fields_from_listing(listing),
            }

        forbidden_subjects = ["语文", "物理", "化学", "生物", "历史", "地理", "政治", "科学", "美术", "钢琴", "编程"]
        for f in forbidden_subjects:
            if f in subject or f in title:
                return {
                    "pass": False,
                    "reason": f"包含未允许学科: {f}",
                    "score": 0.0,
                    "extracted": _extract_fields_from_listing(listing),
                }

        # 2. Compute similarity
        if self.api_url and self.api_key:
            sim = self._api_similarity(conditions, text)
        else:
            sim = self._local_similarity(conditions, text)

        passed = sim >= self.threshold
        reason = (
            f"Embedding 语义相似度 {sim:.4f} >= 阈值 {self.threshold:.4f} (匹配)"
            if passed
            else f"Embedding 语义相似度 {sim:.4f} < 阈值 {self.threshold:.4f} (未达标)"
        )

        return {
            "pass": passed,
            "reason": reason,
            "score": round(sim, 4),
            "extracted": _extract_fields_from_listing(listing),
        }

    def _local_similarity(self, conditions: str, listing_text: str) -> float:
        # Formulate a condensed positive teacher-profile vector
        pos_repr = (
            "男家教老师辅导 小学 初中 高一 数学 小学奥数 英语 英语口语 作业辅导 陪读 陪写作业 课后辅导 "
            + conditions
        )
        v_cond = _tokenize_chinese(pos_repr)
        v_list = _tokenize_chinese(listing_text)
        return _cosine_similarity(v_cond, v_list)

    def _api_similarity(self, text1: str, text2: str) -> float:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "input": [text1, text2],
        }
        req = urllib.request.Request(
            self.api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            e1 = data["data"][0]["embedding"]
            e2 = data["data"][1]["embedding"]
            dot = sum(a * b for a, b in zip(e1, e2))
            norm1 = math.sqrt(sum(a * a for a in e1))
            norm2 = math.sqrt(sum(b * b for b in e2))
            return dot / (norm1 * norm2) if norm1 and norm2 else 0.0
        except Exception:
            return self._local_similarity(text1, text2)
