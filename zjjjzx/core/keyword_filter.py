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


PRESETS: dict[str, dict[str, Any]] = {
    "balanced_math_english": {
        "name": "数英与基础培优 (默认配置)",
        "description": "适合理科/数英家教：小学至高一数学，初一二与高一二英语（排除初三高三中高考冲刺），排除文科与艺术",
        "allowed_subjects": ["数学", "英语", "作业辅导", "作业", "陪读", "陪写作业", "奥数", "全科", "理科"],
        "forbidden_subjects": [
            "语文", "物理", "化学", "生物", "科学", "社会",
            "历史", "地理", "政治", "体育", "羽毛球", "游泳",
            "画画", "美术", "书法", "钢琴", "乐器", "编程", "托管班"
        ],
        "min_grade": 1,
        "max_grade": 10,
        "exclude_keywords": [
            "专职在校老师", "在校老师", "在职老师", "师范类", "师范专业",
            "机构老师", "专四", "专八", "雅思", "托福", "初中竞赛", "高中奥赛", "考研"
        ],
        "special_grade_rules": {
            "英语": {"exclude_grades": [9, 12]}
        },
    },
    "science": {
        "name": "纯理科名师 (数学/物理/化学/生物/奥数)",
        "description": "适合数理化生专业家教：支持初高中理科与竞赛培优，排除所有纯文科与艺术需求",
        "allowed_subjects": ["数学", "物理", "化学", "生物", "科学", "奥数", "理综", "作业辅导"],
        "forbidden_subjects": ["语文", "英语", "历史", "地理", "政治", "音乐", "画画", "美术", "书法", "钢琴", "乐器", "体育"],
        "min_grade": 1,
        "max_grade": 12,
        "exclude_keywords": [
            "专职在校老师", "在校老师", "在职老师", "师范专业", "考研",
        ],
        "special_grade_rules": {},
    },
    "liberal_arts": {
        "name": "文科语言达人 (语文/英语/文综/写作)",
        "description": "适合文科、外语、师范文史类家教：专注中英文读写与文科综合，排除高等理化竞赛",
        "allowed_subjects": ["英语", "语文", "历史", "地理", "政治", "文综", "作文", "阅读", "作业辅导", "陪读"],
        "forbidden_subjects": ["物理", "化学", "生物", "奥数", "高数", "初中竞赛", "高中奥赛"],
        "min_grade": 1,
        "max_grade": 12,
        "exclude_keywords": [
            "专职在校老师", "在校老师", "在职老师", "师范类", "师范专业", "专八", "雅思", "托福",
        ],
        "special_grade_rules": {},
    },
    "primary_homework": {
        "name": "小学全科与晚托陪读 (全科/作业/习惯辅导)",
        "description": "适合大学生课后兼职辅导：专注小学 1-6 年级全科作业检查与陪读，排除初高中所有科目",
        "allowed_subjects": ["作业辅导", "陪读", "陪写作业", "全科", "小学数学", "小学英语", "小学语文", "数学", "英语", "语文"],
        "forbidden_subjects": ["物理", "化学", "生物", "初中", "高中", "中考", "高考", "竞赛"],
        "min_grade": 1,
        "max_grade": 6,
        "exclude_keywords": [
            "专职在校老师", "在校老师", "在职老师", "奥赛", "考研",
        ],
        "special_grade_rules": {},
    },
    "art_sports": {
        "name": "艺体与编程特长 (音乐/美术/书法/球类/少儿编程)",
        "description": "适合艺术、体育或计算机专业家教：专注技能与兴趣特长培养",
        "allowed_subjects": [
            "画画", "美术", "书法", "钢琴", "乐器", "吉他", "古筝", "声乐",
            "体育", "羽毛球", "网球", "游泳", "篮球", "少儿编程", "编程", "Python", "C++", "围棋", "象棋"
        ],
        "forbidden_subjects": ["中考", "高考", "奥赛"],
        "min_grade": 1,
        "max_grade": 12,
        "exclude_keywords": ["专业考级十级必须", "在校在职教研员"],
        "special_grade_rules": {},
    },
    "open": {
        "name": "宽松通用模式 (全学科全学段开放)",
        "description": "不做科目黑白名单拦截，仅根据地图驾车距离与性别做最基础筛选",
        "allowed_subjects": ["*"],
        "forbidden_subjects": [],
        "min_grade": 1,
        "max_grade": 12,
        "exclude_keywords": ["专职在校老师", "在职在编老师"],
        "special_grade_rules": {},
    },
}


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_gender": self.user_gender,
            "min_grade": self.min_grade,
            "max_grade": self.max_grade,
            "allowed_subjects": self.allowed_subjects,
            "forbidden_subjects": self.forbidden_subjects,
            "exclude_keywords": self.exclude_keywords,
            "special_grade_rules": self.special_grade_rules,
            "allow_online": self.allow_online,
            "max_distance_meters": self.max_distance_meters,
        }

    @classmethod
    def from_preset(cls, preset_key: str, **overrides: Any) -> RuleFilterConfig:
        preset_data = PRESETS.get(preset_key, PRESETS["balanced_math_english"])
        merged = {**preset_data, **overrides}
        return cls(
            user_gender=merged.get("user_gender", "男"),
            min_grade=merged.get("min_grade", 1),
            max_grade=merged.get("max_grade", 10),
            allowed_subjects=list(merged.get("allowed_subjects", [])),
            forbidden_subjects=list(merged.get("forbidden_subjects", [])),
            exclude_keywords=list(merged.get("exclude_keywords", [])),
            special_grade_rules=dict(merged.get("special_grade_rules", {})),
            allow_online=bool(merged.get("allow_online", False)),
            max_distance_meters=merged.get("max_distance_meters", 10000.0),
        )

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
            forbidden_subjects=rules.get("forbidden_subjects") if "forbidden_subjects" in rules else [
                "语文", "物理", "化学", "生物", "科学", "社会",
                "历史", "地理", "政治", "体育", "羽毛球", "游泳",
                "画画", "美术", "书法", "钢琴", "乐器", "编程", "托管班",
            ],
            exclude_keywords=rules.get("exclude_keywords") if "exclude_keywords" in rules else [
                "专职在校老师", "在校老师", "在职老师", "师范类", "师范专业",
                "机构老师", "专四", "专八", "雅思", "托福", "初中竞赛", "高中奥赛", "考研",
            ],
            special_grade_rules=rules.get("special_grade_rules") if "special_grade_rules" in rules else {
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
        # 允许列表中若显式包含了某个学科，则优先予以放行，防止与默认黑名单误冲突
        effective_forbidden = [
            forb for forb in cfg.forbidden_subjects
            if forb not in cfg.allowed_subjects
        ]
        for forb in effective_forbidden:
            if forb in text_subject:
                return False, f"包含未开放学科: 【{forb}】"

        # 5. 允许科目检测（必须命中至少一个允许的学科或包含全科/陪读；若包含 '*' 则全科目放行）
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
