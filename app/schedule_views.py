"""日程表页面：整合书院课时间、报名活动时间与地下室预约。"""
from datetime import datetime, timedelta

from app.models import (
    Activity,
    Course,
    CourseParticipant,
    NaturalPerson,
    Participation,
)
from app.view.base import ProfileTemplateView
from Appointment.utils.web_func import get_appoints

__all__ = [
    'mySchedule',
]


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
        events.sort(key=lambda e: e['start'])
        self.extra_context.update(
            html_display=html_display, schedule_events=events)
        return self.get

    def get(self):
        return self.render()
