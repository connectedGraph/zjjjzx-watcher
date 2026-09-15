from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from zjjjzx.core.parser import Listing


GRADE_RANK_MAP: dict[str, int] = {
    "1年级": 1, "一年级": 1, "新1年级": 1, "新一年级": 1,
    "2年级": 2, "二年级": 2, "新2年级": 2, "新二年级": 2,
    "3年级": 3, "三年级": 3, "新3年级": 3, "新三年级": 3,
    "4年级": 4, "四年级": 4, "新4年级": 4, "新四年级": 4,
    "5年级": 5, "五年级": 5, "新5年级": 5, "新五年级": 5,
    "6年级": 6, "六年级": 6, "新6年级": 6, "新六年级": 6,
    "小升初": 6,
    "初一": 7, "初1": 7, "七年级": 7, "7年级": 7, "新初一": 7, "新初1": 7, "新七年级": 7,
    "初二": 8, "初2": 8, "八年级": 8, "8年级": 8, "新初二": 8, "新初2": 8, "新八年级": 8,
    "初三": 9, "初3": 9, "九年级": 9, "9年级": 9, "新初三": 9, "新初3": 9, "新九年级": 9, "中考": 9,
    "高一": 10, "高1": 10, "新高一": 10, "新高1": 10, "初升高": 10,
    "高二": 11, "高2": 11, "新高二": 11, "新高2": 11,
    "高三": 12, "高3": 12, "新高三": 12, "新高3": 12, "高考": 12,
}


def parse_grade_ranks(grade_text: str) -> list[int]:
    clean = grade_text.strip()
    ranks: list[int] = []
    for key, rank in GRADE_RANK_MAP.items():
        if key in clean:
            ranks.append(rank)
    if not ranks:
        if "小学" in clean:
            ranks.extend([1, 2, 3, 4, 5, 6])
        elif "初中" in clean or "初级中学" in clean:
            ranks.extend([7, 8, 9])
        elif "高中" in clean or "高级中学" in clean:
            ranks.extend([10, 11, 12])
    return sorted(list(set(ranks)))


@dataclass
class RuleFilterConfig:
    user_gender: str = "男"
    min_grade: int = 1
    max_grade: int = 10
    allowed_subjects: list[str] = field(
        default_factory=lambda: ["数学", "英语", "作业辅导", "陪读", "陪写作业", "奥数", "全科", "理科"]
    )
    forbidden_subjects: list[str] = field(
        default_factory=lambda: [
            "语文", "物理", "化学", "生物", "科学", "社会",
            "历史", "地理", "政治", "体育", "羽毛球", "游泳",
            "画画", "美术", "书法", "钢琴", "乐器", "编程", "托管班",
        ]
    )
    exclude_keywords: list[str] = field(
        default_factory=lambda: [
            "专职在校老师", "在校老师", "在职老师", "师范类", "师范专业",
            "机构老师", "专四", "专八", "雅思", "托福", "初中竞赛", "高中奥赛", "考研",
        ]
    )
    special_grade_rules: dict[str, Any] = field(
        default_factory=lambda: {
            "英语": {"exclude_grades": [9, 12]}  # 英语不接初三(9)和高三(12)
        }
    )
    allow_online: bool = False
    max_distance_meters: float | None = 10000.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuleFilterConfig:
        rules = data.get("rules", {})
        profile = data.get("profile", {})
        maps = data.get("maps", {})

        return cls(
            user_gender=rules.get("user_gender") or profile.get("user_gender", "男"),
            min_grade=int(rules.get("min_grade", 1)),
            max_grade=int(rules.get("max_grade", 10)),
            allowed_subjects=rules.get("allowed_subjects") or profile.get("subjects") or [
                "数学", "英语", "作业辅导", "陪读", "陪写作业", "奥数", "全科", "理科"
            ],
            forbidden_subjects=rules.get("forbidden_subjects") or [
                "语文", "物理", "化学", "生物", "科学", "社会",
                "历史", "地理", "政治", "体育", "羽毛球", "游泳",
                "画画", "美术", "书法", "钢琴", "乐器", "编程", "托管班",
            ],
            exclude_keywords=rules.get("exclude_keywords") or [
                "专职在校老师", "在校老师", "在职老师", "师范类", "师范专业",
                "机构老师", "专四", "专八", "雅思", "托福", "初中竞赛", "高中奥赛", "考研",
            ],
            special_grade_rules=rules.get("special_grade_rules") or {
                "英语": {"exclude_grades": [9, 12]}
            },
            allow_online=bool(rules.get("allow_online", profile.get("allow_online", False))),
            max_distance_meters=rules.get("max_distance_meters", profile.get("max_distance_meters", 10000.0)),
        )


class KeywordFilter:
    def __init__(self, config: RuleFilterConfig | None = None) -> None:
        self.config = config or RuleFilterConfig()

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> KeywordFilter:
        return cls(RuleFilterConfig.from_dict(config))

    def filter(self, listing: Listing, distance_meters: float | None = None) -> tuple[bool, str]:
        cfg = self.config

        # 1. 授课方式过滤
        if not cfg.allow_online and "线上" in listing.teaching_mode and "线下" not in listing.teaching_mode:
            return False, "不接受纯线上授课"

        # 2. 测距距离过滤 (若提供了距离数据)
        if cfg.max_distance_meters is not None and distance_meters is not None:
            if distance_meters > cfg.max_distance_meters:
                return False, f"距离超出限制 ({distance_meters/1000:.1f}km > {cfg.max_distance_meters/1000:.1f}km)"

        # 3. 性别要求与冲突过滤
        req = listing.requirements or ""
        gender_req = (listing.gender or "").strip()
        title = listing.title or ""
        subject = listing.subject or ""
        full_context = f"{title} {req}"

        # 检查是否为明确男女不限
        is_gender_free = any(
            p in full_context for p in ["男女不限", "男女均可", "男女老师均可", "男女都可以", "不限男女", "男或女均可", "男女皆可"]
        )

        if not is_gender_free:
            if cfg.user_gender == "男":
                female_disqualifiers = [
                    "女老师", "女大学生", "女大", "女性教师", "限女", "女教", "女教员",
                    "仅限女", "最好是女", "只招女", "女专职", "需要女",
                ]
                if gender_req in ("女", "女教师", "女性") or any(w in full_context for w in female_disqualifiers):
                    return False, "性别要求不匹配（家教要求女教师，用户为男性）"
            elif cfg.user_gender == "女":
                male_disqualifiers = [
                    "男老师", "男大学生", "限男", "男教", "男教员", "仅限男", "最好是男", "只招男", "需要男",
                ]
                if gender_req in ("男", "男教师", "男性") or any(w in full_context for w in male_disqualifiers):
                    return False, "性别要求不匹配（家教要求男教师，用户为女性）"

        # 4. 禁用未开放学科检测
        text_subject = f"{title} {subject}"
        for forb in cfg.forbidden_subjects:
            if forb in text_subject:
                return False, f"包含未开放学科: 【{forb}】"

        # 5. 允许科目检测（必须命中至少一个允许的学科或包含全科/陪读）
        if cfg.allowed_subjects and "*" not in cfg.allowed_subjects:
            matched_subject = any(s in subject or s in title for s in cfg.allowed_subjects)
            if not matched_subject:
                return False, f"科目不匹配（家教科目: {subject or title}，允许范围: {', '.join(cfg.allowed_subjects[:4])}...）"

        # 6. 年级段范围与特殊年级规则检测
        ranks = parse_grade_ranks(f"{listing.grade} {title}")
        if ranks:
            if any(r > cfg.max_grade for r in ranks):
                max_rank = max(ranks)
                grade_names = [k for k, v in GRADE_RANK_MAP.items() if v == max_rank]
                return False, f"年级超出范围: {grade_names[0] if grade_names else listing.grade} (上限高一)"
            if any(r < cfg.min_grade for r in ranks):
                return False, f"年级过低: {listing.grade}"

            for subj_key, rule in cfg.special_grade_rules.items():
                if subj_key in subject or subj_key in title:
                    excl_grades = rule.get("exclude_grades", [])
                    if any(r in excl_grades for r in ranks):
                        return False, f"{subj_key}不接受该年级段辅导 (初三/高三排除)"

        # 7. 排除限定关键词检测（如专职在校老师、师范专业、奥赛等）
        for kw in cfg.exclude_keywords:
            if kw in full_context:
                # 特殊兼容：如果需求中明确写了“专职或大学生均可”，则不应被“专职”一票否决
                if any(ok_word in full_context for ok_word in ["或大学生", "大学生均可", "大学生都可以", "大学生也可"]):
                    continue
                return False, f"触发排除限定关键词: 【{kw}】"

        return True, ""
