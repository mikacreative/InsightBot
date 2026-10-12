"""Local-service schedules: explicit times, frozen research, no cron or AI calls."""
from __future__ import annotations

import copy
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


TIMEZONE = 'Asia/Shanghai'
ZONE = ZoneInfo(TIMEZONE)
CONFIG_FIELDS = ('frequency', 'time', 'date', 'weekday', 'window')
WINDOWS = {'fixed', 'last_7_days', 'last_30_days', 'this_month', 'previous_month',
           'this_week', 'previous_week'}
WINDOW_LABELS = {'fixed': '沿用确认方案的时间范围', 'last_7_days': '最近7天',
                 'last_30_days': '最近30天', 'this_month': '本月至触发当天',
                 'previous_month': '上个月', 'this_week': '本周至触发当天', 'previous_week': '上周'}


def instant(value=None):
    value = datetime.now(timezone.utc) if value is None else value
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            raise ValueError('定时时刻格式无效') from None
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('定时时刻须包含时区')
    return value.astimezone(ZONE)


def configuration(value):
    if not isinstance(value, dict) or set(value) - set(CONFIG_FIELDS):
        raise ValueError('自动执行仅支持明确日期、每日或每周时间')
    frequency, clock = value.get('frequency'), value.get('time')
    if frequency not in ('once', 'daily', 'weekly'):
        raise ValueError('请选择一次、每天或每周执行')
    if not isinstance(clock, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
        raise ValueError('执行时间请使用 HH:MM，例如 09:00')
    window = value.get('window', 'fixed')
    if not isinstance(window, str) or window not in WINDOWS:
        raise ValueError('请选择受支持的研究时间范围')
    day, weekday = None, None
    if frequency == 'once':
        try:
            if not isinstance(value.get('date'), str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value['date']):
                raise ValueError('date')
            day = date.fromisoformat(value.get('date')).isoformat()
        except (TypeError, ValueError):
            raise ValueError('一次执行请设置明确日期 YYYY-MM-DD') from None
    if frequency == 'weekly':
        weekday = value.get('weekday')
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ValueError('每周执行请设置星期，周一为0，周日为6')
    return {'frequency': frequency, 'time': clock, 'date': day, 'weekday': weekday, 'window': window}


def next_occurrence(config, after):
    """Strictly future occurrence; restarting or waking up never catches up."""
    config, after = configuration(config), instant(after)
    hour, minute = map(int, config['time'].split(':'))
    day = date.fromisoformat(config['date']) if config['frequency'] == 'once' else after.date()
    if config['frequency'] == 'weekly':
        day += timedelta(days=(config['weekday'] - day.weekday()) % 7)
    candidate = datetime.combine(day, time(hour, minute), ZONE)
    if candidate <= after:
        if config['frequency'] == 'once':
            return None
        candidate += timedelta(days=7 if config['frequency'] == 'weekly' else 1)
    return candidate.isoformat()


def summary(config):
    config = configuration(config)
    when = ('每天' if config['frequency'] == 'daily' else
            '每周' + '一二三四五六日'[config['weekday']] if config['frequency'] == 'weekly' else config['date'])
    return f'{when} {config["time"]}（北京时间）；{WINDOW_LABELS[config["window"]]}。仅在本机服务运行时执行。'


def parse_instruction(instruction, at, default_window='fixed'):
    if not isinstance(instruction, str) or not instruction.strip() or len(instruction) > 1000:
        raise ValueError('自动执行说明请使用不超过1000字的文本')
    text = re.sub(r'\s+', '', instruction.strip()).replace('：', ':').rstrip('。.!！')
    window = default_window
    window_match = re.search(r'[，,]?(?:看|研究|窗口为|范围为)?(最近7天|近7天|过去7天|最近30天|近30天|本月|上月|本周|上周)'
                             r'(?:的)?(?:讨论|内容|样本|数据|笔记)?$', text)
    if window_match:
        phrase = window_match[1]
        window = ('last_7_days' if '7天' in phrase else 'last_30_days' if '30天' in phrase else
                  {'本月': 'this_month', '上月': 'previous_month', '本周': 'this_week', '上周': 'previous_week'}[phrase])
        text = text[:window_match.start()]
    text = re.sub(r'^(?:请|帮我|以后|从现在起|改成|改为|设为|设置为)+', '', text)
    text = re.sub(r'(?:自动执行|执行一次|执行|自动研究|开始研究|自动运行|运行一次|运行)$', '', text)
    match = re.fullmatch(r'(每天|每日|每周[一二三四五六日天]|\d{4}-\d{2}-\d{2}|\d{4}年\d{1,2}月\d{1,2}日|明天|后天|今天)'
                         r'(上午|早上|下午|晚上|中午|凌晨)?(\d{1,2}|[一二三四五六七八九十零两]{1,3})'
                         r'(?::([0-5]\d)|点(?:(半)|([0-5]?\d)分?)?)', text)
    if not match:
        return None
    period, meridiem, raw_hour, minute, half, raw_minute = match.groups()
    chinese = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5,
               '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    if raw_hour.isdigit():
        hour = int(raw_hour)
    elif raw_hour in chinese:
        hour = chinese[raw_hour]
    elif raw_hour.count('十') == 1:
        left, right = raw_hour.split('十')
        if (left and left not in chinese) or (right and right not in chinese):
            return None
        hour = (chinese[left] if left else 1) * 10 + (chinese[right] if right else 0)
    else:
        return None
    if meridiem in ('下午', '晚上'):
        if not 1 <= hour <= 12:
            return None
        hour = hour if hour == 12 else hour + 12
    elif meridiem in ('上午', '早上', '凌晨') and not 0 <= hour <= 11:
        return None
    elif meridiem == '中午' and hour not in (11, 12, 1):
        return None
    elif meridiem == '中午' and hour == 1:
        hour = 13
    if not 0 <= hour <= 23:
        return None
    config = {'frequency': 'daily', 'time': f'{hour:02}:{int(minute or raw_minute or (30 if half else 0)):02}', 'window': window}
    if period.startswith('每周'):
        config.update(frequency='weekly', weekday='一二三四五六日'.find(period[-1]) if period[-1] != '天' else 6)
    elif period not in ('每天', '每日'):
        if period in ('今天', '明天', '后天'):
            day = instant(at).date() + timedelta(days={'今天': 0, '明天': 1, '后天': 2}[period])
        else:
            normalized = re.sub(r'[年月]', '-', period).rstrip('日')
            try:
                year, month, day_number = map(int, normalized.split('-'))
                day = date(year, month, day_number)
            except ValueError:
                return None
        config.update(frequency='once', date=day.isoformat())
    return configuration(config)


def research_window(window, at):
    today = instant(at).date()
    if window == 'last_7_days' or window == 'last_30_days':
        return today - timedelta(days=6 if window == 'last_7_days' else 29), today
    if window == 'this_month':
        return today.replace(day=1), today
    if window == 'previous_month':
        end = today.replace(day=1) - timedelta(days=1)
        return end.replace(day=1), end
    if window == 'this_week':
        return today - timedelta(days=today.weekday()), today
    if window == 'previous_week':
        end = today - timedelta(days=today.weekday() + 1)
        return end - timedelta(days=6), end
    raise ValueError('研究时间范围无效')


def frozen_run(plan, window, at):
    """Change only query/window dates; never replan or alter a paid allowance."""
    result = copy.deepcopy(plan)
    if window == 'fixed':
        return result
    start, end = research_window(window, at)
    result.update(start_date=start.isoformat(), end_date=end.isoformat())
    for query in result['queries']:
        query_start, query_end = start, end
        if query.get('period') == 'previous':
            query_end = start - timedelta(days=1)
            query_start = query_end - (end - start)
        query.update(start_date=query_start.isoformat(), end_date=query_end.isoformat())
    return result
