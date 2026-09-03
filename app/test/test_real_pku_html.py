"""
用真实的「北京大学校内信息门户.html」（门户「我的课表」另存为）做端到端解析校验。

该文件是同学提供的真实课表样例，覆盖：
- 同名课程跨多天（高等数学 周二+周四、概率统计 周三单周+周五每周、程序设计 周三+周五单周、
  人工智能基础 周一+周四单周）-> 13 条课程块、9 个不同课名；
- 单/双周、无教室（体适能）、多教师逗号名单（中国近现代史纲要）；
- 1-16 周（人工智能时代的超级个体）与 1-15 周混合。

测试文件若不存在则跳过（CI 可能未包含该样例），不影响其余用例。
"""
import os
import unittest
from datetime import date, datetime, timedelta

from django.test import TestCase

from app.pku_course_parser import expand_lesson_to_events, parse_pku_course_html

_PORTAL_HTML = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),  # repo root
    "北京大学校内信息门户.html",
)


@unittest.skipUnless(os.path.exists(_PORTAL_HTML), "缺少真实课表样例 HTML，跳过")
class RealPkuHtmlParseTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        raw = open(_PORTAL_HTML, encoding="utf-8", errors="ignore").read()
        cls.lessons = parse_pku_course_html(raw)
        cls.future_monday = date.today() + timedelta(
            days=(7 - date.today().weekday()) % 7 or 7)

    def test_lesson_blocks(self):
        # 13 条课程块（含同名跨天）
        self.assertEqual(len(self.lessons), 13)

    def test_distinct_course_names(self):
        names = {L["name"] for L in self.lessons}
        # 9 个不同课名：高等数学/概率统计/程序设计/人工智能基础 各跨两天
        self.assertEqual(len(names), 9)
        for expected in ("高等数学A（二）", "概率统计 （A）", "程序设计实习",
                         "人工智能基础", "国外社会学学说（上）", "中国近现代史纲要",
                         "体适能", "英语散文选读：19世纪维多利亚时期至20世纪",
                         "人工智能时代的超级个体：从零开始AI编程实战"):
            self.assertIn(expected, names)

    def test_parity_split_same_name(self):
        gailv = [L for L in self.lessons if L["name"] == "概率统计 （A）"]
        self.assertEqual({g["parity"] for g in gailv}, {"ALL", "ODD"})

    def test_no_room_course(self):
        ti = [L for L in self.lessons if L["name"] == "体适能"][0]
        self.assertEqual(ti["room"], "")
        self.assertEqual(ti["day_of_week"], 1)  # 周二
        self.assertEqual((ti["start_section"], ti["end_section"]), (3, 4))

    def test_multi_teacher(self):
        zg = [L for L in self.lessons if L["name"] == "中国近现代史纲要"][0]
        self.assertIn("冯雅新", zg["teacher"])
        self.assertIn(",", zg["teacher"])

    def test_expand_future_count(self):
        # 每周9门×15 + 超级个体1-16周×16 + 单周3门×8(1,3,5,7,9,11,13,15) = 135+16+24 = 175
        total = sum(len(expand_lesson_to_events(L, self.future_monday))
                   for L in self.lessons)
        self.assertEqual(total, 175)

    def test_expand_past_empty(self):
        past = date(2026, 2, 23)
        total = sum(len(expand_lesson_to_events(L, past)) for L in self.lessons)
        self.assertEqual(total, 0)
