"""日程表页面：整合书院课时间、报名活动时间与地下室预约。"""
from datetime import datetime, timedelta

from app.models import (
    AcademicCourse,
    Activity,
    Course,
    CourseParticipant,
    NaturalPerson,
    Participation,
)
from app.pku_course_parser import expand_lesson_to_events, parse_pku_course_html
from app.view.base import ProfileTemplateView
from Appointment.utils.web_func import get_appoints
from utils.global_messages import succeed, wrong

__all__ = [
    'mySchedule',
    'importCourseTable',
]

# 上传页允许的最大文件体积（门户课表 HTML 通常 < 200KB）
_MAX_UPLOAD_BYTES = 2 * 1024 * 1024
# 单双周字符 -> AcademicCourse.Parity 整数
_PARITY_MAP = {'ALL': AcademicCourse.Parity.ALL,
               'ODD': AcademicCourse.Parity.ODD,
               'EVEN': AcademicCourse.Parity.EVEN}


class mySchedule(ProfileTemplateView):
    """个人日程表，聚合三类来源的时间安排。"""

    template_name = 'schedule/index.html'
    page_name = '我的日程表'
    http_method_names = ['get']

    # 三源事件配色
    _COLOR_COURSE = '#4361ee'        # 书院课程（已发布活动）
    _COLOR_PLANNED = '#8ba3f0'       # 书院课表（尚未发布活动的周次）
    _COLOR_ACTIVITY = '#2ecc71'      # 报名活动
    _COLOR_APPOINT = '#f39c12'       # 地下室预约
    _COLOR_ACADEMIC = '#9b59b6'      # 教务课表（门户导入）

    def _collect_participation_events(self, me: NaturalPerson):
        """已报名/已选课且活动已生成的日程。"""
        now = datetime.now()
        events = []
        participations = (
            Participation.objects.activated()
            .filter(person=me, activity__end__gt=now)
            .exclude(activity__status__in=[
                Activity.Status.CANCELED,
                Activity.Status.ABORT,
            ])
            .select_related('activity')
        )
        for p in participations:
            act = p.activity
            if act.category == Activity.ActivityCategory.COURSE:
                color, category = self._COLOR_COURSE, '书院课程'
            else:
                color, category = self._COLOR_ACTIVITY, '报名活动'
            events.append({
                'title': act.title,
                'start': act.start.strftime('%Y-%m-%dT%H:%M:%S'),
                'end': act.end.strftime('%Y-%m-%dT%H:%M:%S'),
                'color': color,
                'category': category,
                'location': act.location or '未设置',
                'url': f'/viewActivity/{act.id}',
            })
        return events

    def _collect_planned_course_events(self, me: NaturalPerson):
        """课表：已选上但尚未发布课程活动的未来周次。

        课程活动由定时任务逐周生成（CourseTime.cur_week 记录已生成周数），
        因此仅靠活动无法展示整学期课表，这里按周展开补全。
        """
        now = datetime.now()
        events = []
        courses = Course.objects.activated().filter(
            participant_set__person=me,
            participant_set__status=CourseParticipant.Status.SUCCESS,
        ).prefetch_related('time_set')
        for course in courses:
            for course_time in course.time_set.all():
                # 已生成的周次为 [0, cur_week)，其余周次尚未产生活动
                for week in range(course_time.cur_week, course_time.end_week):
                    start = course_time.start + timedelta(days=7 * week)
                    end = course_time.end + timedelta(days=7 * week)
                    if end <= now:
                        continue
                    events.append({
                        'title': course.name,
                        'start': start.strftime('%Y-%m-%dT%H:%M:%S'),
                        'end': end.strftime('%Y-%m-%dT%H:%M:%S'),
                        'color': self._COLOR_PLANNED,
                        'category': '书院课表（未发布）',
                        'location': '以课程活动发布为准',
                    })
        return events

    def _collect_appointment_events(self, user):
        """地下室房间预约。"""
        events = []
        appoints = get_appoints(user, 'future')
        if not appoints:
            return events
        for appoint in appoints.select_related('Room'):
            room = appoint.Room.Rtitle if appoint.Room_id else '未知房间'
            events.append({
                'title': f'地下室：{room}',
                'start': appoint.Astart.strftime('%Y-%m-%dT%H:%M:%S'),
                'end': appoint.Afinish.strftime('%Y-%m-%dT%H:%M:%S'),
                'color': self._COLOR_APPOINT,
                'category': '地下室预约',
                'location': room,
                'url': '/underground/',
            })
        return events

    def _collect_academic_course_events(self, me: NaturalPerson):
        """教务课表（同学从门户导入）。按周展开为日历事件。"""
        now = datetime.now()
        events = []
        courses = AcademicCourse.objects.filter(person=me)
        for course in courses:
            semester_start = course.semester_start
            parity = {AcademicCourse.Parity.ALL: 'ALL',
                      AcademicCourse.Parity.ODD: 'ODD',
                      AcademicCourse.Parity.EVEN: 'EVEN'}[course.parity]
            lesson = {
                'day_of_week': course.day_of_week,
                'start_section': course.start_section,
                'end_section': course.end_section,
                'start_time': course.start_time.strftime('%H:%M'),
                'end_time': course.end_time.strftime('%H:%M'),
                'week_start': course.week_start,
                'week_end': course.week_end,
                'parity': parity,
                'name': course.name,
                'room': course.room,
                'teacher': course.teacher,
            }
            for ev in expand_lesson_to_events(lesson, semester_start, now):
                ev.update({
                    'color': self._COLOR_ACADEMIC,
                    'category': '教务课表',
                })
                events.append(ev)
        return events

    def prepare_get(self):
        html_display = {}
        if not self.request.user.is_person():
            html_display['warn_code'] = 1
            html_display['warn_message'] = '日程表仅对个人用户开放！'
            self.extra_context.update(
                html_display=html_display, schedule_events=[])
            return self.get

        me = NaturalPerson.objects.get(person_id=self.request.user)
        events = self._collect_participation_events(me)
        events += self._collect_planned_course_events(me)
        events += self._collect_appointment_events(self.request.user)
        events += self._collect_academic_course_events(me)
        events.sort(key=lambda e: e['start'])
        self.extra_context.update(
            html_display=html_display, schedule_events=events)
        return self.get

    def get(self):
        return self.render()


class importCourseTable(ProfileTemplateView):
    """导入教务课表：上传门户「我的课表」HTML，解析后存入本人课表。"""

    template_name = 'schedule/upload.html'
    page_name = '导入教务课表'
    http_method_names = ['get', 'post']

    def prepare_get(self):
        self.extra_context['html_display'] = {}
        return self.get

    def prepare_post(self):
        html_display = {}
        if not self.request.user.is_person():
            wrong('导入课表仅对个人用户开放！', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        me = NaturalPerson.objects.get(person_id=self.request.user)

        # 1) 读取上传文件（仅在内存中解析，绝不落盘）
        upload = self.request.FILES.get('course_html')
        if upload is None or upload.size == 0:
            wrong('请先选择门户课表 HTML 文件再上传。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post
        if upload.size > _MAX_UPLOAD_BYTES:
            wrong('文件过大，请确保上传的是门户课表页面（.html）。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post
        try:
            raw = upload.read().decode('utf-8', errors='ignore')
        except Exception:
            wrong('文件读取失败，请确认上传的是有效的 HTML 文件。', html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 2) 学期第一周周一（必填）
        semester_start_str = (self.request.POST.get('semester_start') or '').strip()
        try:
            semester_start = datetime.strptime(
                semester_start_str, '%Y-%m-%d').date()
        except Exception:
            wrong('请填写学期第 1 教学周对应的周一日期（格式 YYYY-MM-DD）。',
                  html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 3) 解析
        lessons = parse_pku_course_html(raw)
        if not lessons:
            wrong('未能从文件中解析到课程，请确认上传的是门户「我的课表」页面。',
                  html_display)
            self.extra_context.update(html_display=html_display)
            return self.post

        # 4) 覆盖式写入（同一同学重新导入即替换）
        term = (self.request.POST.get('term') or '').strip()
        AcademicCourse.objects.filter(person=me).delete()
        for lesson in lessons:
            AcademicCourse.objects.create(
                person=me,
                name=lesson['name'],
                teacher=lesson['teacher'],
                room=lesson['room'],
                day_of_week=lesson['day_of_week'],
                start_section=lesson['start_section'],
                end_section=lesson['end_section'],
                start_time=datetime.strptime(
                    lesson['start_time'], '%H:%M').time(),
                end_time=datetime.strptime(
                    lesson['end_time'], '%H:%M').time(),
                week_start=lesson['week_start'],
                week_end=lesson['week_end'],
                parity=_PARITY_MAP.get(lesson['parity'], AcademicCourse.Parity.ALL),
                semester_start=semester_start,
                term=term,
            )

        succeed(f'已成功导入 {len(lessons)} 门课程，可在「我的日程表」查看。',
                 html_display)
        self.extra_context.update(html_display=html_display)
        return self.post

    def get(self):
        return self.render()

    def post(self):
        return self.render()
