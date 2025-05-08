import pytest
from datetime import datetime, timedelta
import pytz
from freezegun import freeze_time

# テスト対象の関数を bot.py からインポート
# bot.py がプロジェクトルートにあると仮定
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from bot import parse_time_string

# テストで使用するタイムゾーン
TEST_TIMEZONE = pytz.timezone("Asia/Tokyo")

# テストの基準となる現在時刻 (freezegunで固定)
FROZEN_TIME_STR = "2024-05-09 10:00:00"
FROZEN_DATETIME = TEST_TIMEZONE.localize(datetime.strptime(FROZEN_TIME_STR, '%Y-%m-%d %H:%M:%S'))

@pytest.fixture
def now():
    """テストで使用する固定された現在時刻 (aware)"""
    return FROZEN_DATETIME

@freeze_time(FROZEN_TIME_STR)
def test_parse_absolute_time(now):
    """絶対時刻指定 (YYYY/MM/DD HH:MM) のテスト"""
    # 未来の時刻
    dt, recurring, rule = parse_time_string("2024/12/31 23:59", now)
    expected_dt = TEST_TIMEZONE.localize(datetime(2024, 12, 31, 23, 59))
    assert dt == expected_dt
    assert recurring is False
    assert rule is None

    # 過去の時刻 (現在はエラーにならないが、未来化されるか確認 -> parse_time_stringの実装による)
    # 現状の実装では過去日付指定は未来化されないはず
    dt_past, _, _ = parse_time_string("2023/01/01 10:00", now)
    expected_dt_past = TEST_TIMEZONE.localize(datetime(2023, 1, 1, 10, 0))
    # 注意: 呼び出し元 (slash_set_reminder) で過去時刻チェックが行われる
    assert dt_past == expected_dt_past 

@freeze_time(FROZEN_TIME_STR)
def test_parse_today_time(now):
    """当日時刻指定 (HH:MM) のテスト"""
    # 未来の時刻 (今日の15:30)
    dt, recurring, rule = parse_time_string("15:30", now)
    expected_dt = now.replace(hour=15, minute=30, second=0, microsecond=0)
    assert dt == expected_dt
    assert recurring is False
    assert rule is None

    # 過去の時刻 (今日の09:30 -> 明日の09:30になるはず)
    dt_past, recurring_past, rule_past = parse_time_string("09:30", now)
    expected_dt_past = (now + timedelta(days=1)).replace(hour=9, minute=30, second=0, microsecond=0)
    assert dt_past == expected_dt_past
    assert recurring_past is False
    assert rule_past is None

@freeze_time(FROZEN_TIME_STR)
def test_parse_relative_time(now):
    """相対時刻指定 (in X unit) のテスト"""
    # 30分後
    dt_min, r_min, rl_min = parse_time_string("in 30 minutes", now)
    assert dt_min == now + timedelta(minutes=30)
    assert r_min is False
    assert rl_min is None

    # 2時間後
    dt_hr, r_hr, rl_hr = parse_time_string("in 2 hours", now)
    assert dt_hr == now + timedelta(hours=2)
    assert r_hr is False
    assert rl_hr is None

    # 5日後
    dt_day, r_day, rl_day = parse_time_string("in 5 days", now)
    assert dt_day == now + timedelta(days=5)
    assert r_day is False
    assert rl_day is None

@freeze_time(FROZEN_TIME_STR)
def test_parse_tomorrow_time(now):
    """明日以降の時刻指定 (tomorrow at HH:MM) のテスト"""
    dt, recurring, rule = parse_time_string("tomorrow at 14:00", now)
    expected_dt = (now + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    assert dt == expected_dt
    assert recurring is False
    assert rule is None

@freeze_time(FROZEN_TIME_STR) # 2024-05-09 は木曜日 (weekday=3)
def test_parse_recurring_daily(now):
    """繰り返し指定 (every day at HH:MM) のテスト"""
    # 未来時刻 (今日の11:00)
    dt, recurring, rule = parse_time_string("every day at 11:00", now)
    expected_dt = now.replace(hour=11, minute=0, second=0, microsecond=0)
    assert dt == expected_dt
    assert recurring is True
    assert rule == "FREQ=DAILY;BYHOUR=11;BYMINUTE=0"

    # 過去時刻 (今日の09:00 -> 明日の09:00)
    dt_past, recurring_past, rule_past = parse_time_string("every day at 09:00", now)
    expected_dt_past = (now + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    assert dt_past == expected_dt_past
    assert recurring_past is True
    assert rule_past == "FREQ=DAILY;BYHOUR=9;BYMINUTE=0"

@freeze_time(FROZEN_TIME_STR) # 2024-05-09 は木曜日 (weekday=3)
def test_parse_recurring_weekly(now):
    """繰り返し指定 (every weekday at HH:MM) のテスト"""
    # 未来の曜日 (金曜日 10:00) -> 明日
    dt_fri, r_fri, rl_fri = parse_time_string("every friday at 10:00", now)
    expected_dt_fri = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    assert dt_fri == expected_dt_fri
    assert r_fri is True
    assert rl_fri == "FREQ=WEEKLY;BYDAY=FR;BYHOUR=10;BYMINUTE=0" # BYHOUR/BYMINUTEも含むように修正

    # 過去の曜日 (月曜日 10:00) -> 来週の月曜日
    dt_mon, r_mon, rl_mon = parse_time_string("every monday at 10:00", now)
    # 5/9(木) -> 5/13(月) は 4日後
    expected_dt_mon = (now + timedelta(days=4)).replace(hour=10, minute=0, second=0, microsecond=0)
    assert dt_mon == expected_dt_mon
    assert r_mon is True
    assert rl_mon == "FREQ=WEEKLY;BYDAY=MO;BYHOUR=10;BYMINUTE=0"

    # 今日の曜日だが過去時刻 (木曜日 09:00) -> 来週の木曜日
    dt_thu, r_thu, rl_thu = parse_time_string("every thursday at 09:00", now)
    expected_dt_thu = (now + timedelta(days=7)).replace(hour=9, minute=0, second=0, microsecond=0)
    assert dt_thu == expected_dt_thu
    assert r_thu is True
    assert rl_thu == "FREQ=WEEKLY;BYDAY=TH;BYHOUR=9;BYMINUTE=0"

    # 今日の曜日で未来時刻 (木曜日 11:00) -> 今日の11:00
    dt_thu_future, r_thu_future, rl_thu_future = parse_time_string("every thursday at 11:00", now)
    expected_dt_thu_future = now.replace(hour=11, minute=0, second=0, microsecond=0)
    assert dt_thu_future == expected_dt_thu_future
    assert r_thu_future is True
    assert rl_thu_future == "FREQ=WEEKLY;BYDAY=TH;BYHOUR=11;BYMINUTE=0"


@freeze_time(FROZEN_TIME_STR)
def test_parse_with_dateutil(now):
    """dateutil.parserによるフォールバックパースのテスト"""
    # "May 10 2024 15:00" のような形式
    dt, recurring, rule = parse_time_string("May 10 2024 15:00", now)
    expected_dt = TEST_TIMEZONE.localize(datetime(2024, 5, 10, 15, 0))
    assert dt == expected_dt
    assert recurring is False
    assert rule is None

    # "next friday at 3pm" (これは現状の正規表現ではマッチせず、dateutilに渡る)
    # dateutil.parser は "next friday" を解釈できる
    dt_next, r_next, rl_next = parse_time_string("next friday at 3pm", now)
    # 5/9(木) の次の金曜日は 5/10
    expected_dt_next = TEST_TIMEZONE.localize(datetime(2024, 5, 10, 15, 0))
    assert dt_next == expected_dt_next
    assert r_next is False
    assert rl_next is None

@freeze_time(FROZEN_TIME_STR)
def test_parse_invalid_format(now):
    """無効なフォーマットのテスト"""
    assert parse_time_string("invalid time format", now) == (None, False, None)
    assert parse_time_string("in 5 parsecs", now) == (None, False, None)
    assert parse_time_string("every 2 days at 10", now) == (None, False, None) # 未対応形式
    assert parse_time_string("tomorrow", now) == (None, False, None) # 時刻がない
