import unittest

from zjjjzx.core.keyword_filter import (
    KeywordFilter,
    RuleFilterConfig,
    parse_grade_ranks,
)
from zjjjzx.core.parser import Listing


def make_test_listing(
    external_id: str = "t1",
    title: str = "测试家教",
    grade: str = "初一",
    subject: str = "数学",
    teaching_mode: str = "上门",
    gender: str = "不限",
    requirements: str = "认真负责",
    address: str = "宁波市鄞州区",
) -> Listing:
    return Listing(
        external_id=external_id,
        site_job_id="101",
        title=title,
        grade=grade,
        subject=subject,
        price_text="100元/时",
        price_value=100.0,
        address=address,
        teaching_mode=teaching_mode,
        gender=gender,
        teaching_time="周六上午",
        requirements=requirements,
        publish_date="2026-09-16",
        detail_url="https://zjjjzx.com/teacher/",
        raw_text=f"{title} {requirements}",
    )


class KeywordFilterTests(unittest.TestCase):
    def setUp(self):
        self.config = RuleFilterConfig(
            user_gender="男",
            min_grade=1,
            max_grade=10,
            allowed_subjects=["数学", "英语", "作业辅导", "陪读", "陪写作业", "奥数", "全科", "理科"],
            forbidden_subjects=["语文", "物理", "化学", "生物", "科学", "社会", "体育", "美术"],
            exclude_keywords=["专职在校老师", "在校老师", "在职老师", "师范专业", "专八", "雅思", "考研"],
            special_grade_rules={"英语": {"exclude_grades": [9, 12]}},
            allow_online=False,
            max_distance_meters=10000.0,
        )
        self.filter = KeywordFilter(self.config)

    def test_parse_grade_ranks(self):
        self.assertEqual(parse_grade_ranks("五年级"), [5])
        self.assertEqual(parse_grade_ranks("初一"), [7])
        self.assertEqual(parse_grade_ranks("初三"), [9])
        self.assertEqual(parse_grade_ranks("高一"), [10])
        self.assertEqual(parse_grade_ranks("高二"), [11])
        self.assertEqual(parse_grade_ranks("小升初"), [6])
        self.assertEqual(parse_grade_ranks("初中"), [7, 8, 9])
        self.assertEqual(parse_grade_ranks("未知年级"), [])

    def test_grade_range_rejection(self):
        # Grade 11 (高二) exceeds max_grade 10 (高一)
        listing_high2 = make_test_listing(grade="高二", subject="数学", title="高二数学辅导")
        passed, reason = self.filter.filter(listing_high2, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("年级超出范围", reason)

        # Grade 10 (高一) should pass
        listing_high1 = make_test_listing(grade="高一", subject="数学", title="高一数学辅导")
        passed, reason = self.filter.filter(listing_high1, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_special_grade_rule_english(self):
        # 英语初三 (Grade 9) excluded by special rule
        listing_eng_g9 = make_test_listing(grade="初三", subject="英语", title="初三英语冲刺")
        passed, reason = self.filter.filter(listing_eng_g9, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("初三/高三排除", reason)

        # 英语初二 (Grade 8) should pass
        listing_eng_g8 = make_test_listing(grade="初二", subject="英语", title="初二英语同步辅导")
        passed, reason = self.filter.filter(listing_eng_g8, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_gender_filtering(self):
        # Female teacher required explicitly in gender field
        listing_fem = make_test_listing(gender="女", requirements="认真负责")
        passed, reason = self.filter.filter(listing_fem, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("性别要求不匹配", reason)

        # Female teacher required in requirements text
        listing_fem_text = make_test_listing(gender="不限", requirements="需要女老师，有耐心")
        passed, reason = self.filter.filter(listing_fem_text, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("性别要求不匹配", reason)

        # Student is girl, teacher gender unrestricted -> should PASS
        listing_girl_student = make_test_listing(
            gender="不限",
            requirements="辅导初一女孩子数学作业，男女不限，大学生均可",
        )
        passed, reason = self.filter.filter(listing_girl_student, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_subject_rules(self):
        # Forbidden subject: 物理
        listing_phys = make_test_listing(subject="物理", title="初二物理辅导")
        passed, reason = self.filter.filter(listing_phys, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("包含未开放学科", reason)

        # Non-allowed subject: 编程
        listing_prog = make_test_listing(subject="少儿编程", title="Python编程教学")
        passed, reason = self.filter.filter(listing_prog, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("科目不匹配", reason)

        # Allowed subjects: 全科 / 作业辅导
        listing_homework = make_test_listing(subject="作业辅导", title="小学四年级作业辅导陪读")
        passed, reason = self.filter.filter(listing_homework, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_exclude_keywords(self):
        # High qualification requirement: 专职在校老师
        listing_teacher = make_test_listing(requirements="要求专职在校老师辅导，机构名师优先")
        passed, reason = self.filter.filter(listing_teacher, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("触发排除限定关键词", reason)

        # Exception: 专职或大学生均可 -> should NOT be rejected by "专职"
        listing_exception = make_test_listing(requirements="在校老师或大学生均可，重点是要有耐心")
        passed, reason = self.filter.filter(listing_exception, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_distance_and_mode_rules(self):
        # Distance exceeded
        listing_far = make_test_listing()
        passed, reason = self.filter.filter(listing_far, distance_meters=15000)
        self.assertFalse(passed)
        self.assertIn("距离超出限制", reason)

        # Pure online teaching mode rejected
        listing_online = make_test_listing(teaching_mode="线上辅导")
        passed, reason = self.filter.filter(listing_online, distance_meters=3000)
        self.assertFalse(passed)
        self.assertIn("不接受纯线上授课", reason)

    def test_presets_loading_and_customization(self):
        from zjjjzx.core.keyword_filter import PRESETS
        self.assertIn("science", PRESETS)
        self.assertIn("liberal_arts", PRESETS)
        self.assertIn("primary_homework", PRESETS)
        self.assertIn("open", PRESETS)

        # Test science preset: allows 物理 and 数学, forbids 语文
        sci_cfg = RuleFilterConfig.from_preset("science", user_gender="男")
        sci_filter = KeywordFilter(sci_cfg)
        listing_phys = make_test_listing(subject="物理", title="高二物理培优辅导", grade="高二")
        passed, reason = sci_filter.filter(listing_phys, distance_meters=3000)
        self.assertTrue(passed, reason)

        # Test liberal arts preset: allows 语文, forbids 物理
        arts_cfg = RuleFilterConfig.from_preset("liberal_arts", user_gender="女")
        arts_filter = KeywordFilter(arts_cfg)
        listing_chinese = make_test_listing(subject="语文", title="初一语文阅读与写作", grade="初一", gender="女")
        passed, reason = arts_filter.filter(listing_chinese, distance_meters=3000)
        self.assertTrue(passed, reason)

    def test_effective_forbidden_override(self):
        # If user explicitly adds 物理 to allowed_subjects, it should override default forbidden_subjects
        cfg = RuleFilterConfig(
            allowed_subjects=["物理", "数学"],
            forbidden_subjects=["物理", "化学", "语文"],  # 物理 in both!
        )
        kf = KeywordFilter(cfg)
        listing = make_test_listing(subject="物理", title="初二物理辅导", grade="初二")
        passed, reason = kf.filter(listing, distance_meters=2000)
        self.assertTrue(passed, reason)

    def test_open_preset_allows_any_subject(self):
        open_cfg = RuleFilterConfig.from_preset("open")
        open_filter = KeywordFilter(open_cfg)
        listing_art = make_test_listing(subject="小提琴", title="少儿小提琴启蒙", grade="三年级")
        passed, reason = open_filter.filter(listing_art, distance_meters=2000)
        self.assertTrue(passed, reason)


if __name__ == "__main__":
    unittest.main()
