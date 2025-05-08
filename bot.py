import discord
from discord.ext import commands, tasks
import os
import sqlite3
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
import logging
from dotenv import load_dotenv
import re
from dateutil.parser import parse as dateutil_parse

logging.basicConfig(level=logging.INFO)

load_dotenv()
DISCORD_BOT_TOKEN = os.getenv('DISCORD_BOT_TOKEN')
DISCORD_TEST_GUILD_ID = os.getenv('DISCORD_TEST_GUILD_ID') # テスト用ギルドID (任意)

if not DISCORD_BOT_TOKEN:
    logging.error("DISCORD_BOT_TOKENが.envファイルに設定されていません。")
    exit()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

class RemindBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)

    async def setup_hook(self):
        if DISCORD_TEST_GUILD_ID:
            try:
                guild_id = int(DISCORD_TEST_GUILD_ID)
                guild_obj = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild_obj)
                await self.tree.sync(guild=guild_obj)
                logging.info(f"コマンドをテストギルド {guild_id} に同期しました。")
            except ValueError:
                logging.error(f"環境変数 DISCORD_TEST_GUILD_ID の値が無効です: {DISCORD_TEST_GUILD_ID}。グローバル同期にフォールバックします。")
                await self.tree.sync()
                logging.info("コマンドをグローバルに同期しました。")
        else:
            await self.tree.sync()
            logging.info("コマンドをグローバルに同期しました。反映に時間がかかる場合があります。")

bot = RemindBot()

DB_PATH = 'data/reminders.db'
DB_DIR = 'data'

def init_db():
    """データベースを初期化し、remindersテーブルを作成する"""
    if not os.path.exists(DB_DIR):
        os.makedirs(DB_DIR)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            guild_id TEXT NOT NULL,
            channel_id TEXT NOT NULL,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            message TEXT NOT NULL,
            trigger_time DATETIME NOT NULL,
            is_recurring BOOLEAN NOT NULL DEFAULT 0,
            recurrence_rule TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("データベースが初期化されました。")

scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")

async def send_reminder(reminder_id: int):
    """指定されたIDのリマインドを送信し、必要であれば再スケジュールする"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    reminder = cursor.fetchone()

    if not reminder:
        logging.warning(f"リマインドID {reminder_id} が見つかりませんでした。ジョブを削除します。")
        try:
            scheduler.remove_job(str(reminder_id))
        except Exception as e:
            logging.error(f"ジョブ {reminder_id} の削除に失敗しました: {e}")
        conn.close()
        return

    target_type = reminder['target_type']
    target_id = reminder['target_id']
    message_content = reminder['message']
    guild_id = reminder['guild_id']
    is_recurring = reminder['is_recurring']
    recurrence_rule = reminder['recurrence_rule']

    guild = bot.get_guild(int(guild_id))
    if not guild:
        logging.error(f"サーバー {guild_id} が見つかりません。リマインドID: {reminder_id}")
        conn.close()
        return

    target = None
    if target_type == 'user':
        try:
            target = await guild.fetch_member(int(target_id))
            if not target:
                target = await bot.fetch_user(int(target_id))
        except discord.NotFound:
            logging.warning(f"ユーザー {target_id} がサーバー {guild_id} に見つかりません。リマインドID: {reminder_id}")
            try:
                target = await bot.fetch_user(int(target_id))
            except discord.NotFound:
                 logging.error(f"ユーザー {target_id} が見つかりません。リマインドID: {reminder_id}")
                 conn.close()
                 return
        except Exception as e:
            logging.error(f"ユーザー {target_id} の取得中にエラー: {e}。リマインドID: {reminder_id}")
            conn.close()
            return
    elif target_type == 'channel':
        target = guild.get_channel(int(target_id))
        if not target:
             logging.warning(f"チャンネル {target_id} がサーバー {guild_id} に見つかりません。リマインドID: {reminder_id}")
             conn.close()
             return
    else:
        logging.error(f"不明なターゲットタイプ: {target_type}。リマインドID: {reminder_id}")
        conn.close()
        return

    if target:
        try:
            await target.send(f"リマインダー: {message_content}")
            logging.info(f"リマインド送信完了: ID {reminder_id}, 宛先 {target_type} {target_id}, メッセージ「{message_content}」")
        except discord.Forbidden:
            logging.error(f"リマインド送信失敗 (権限不足): ID {reminder_id}, 宛先 {target_type} {target_id}")
        except Exception as e:
            logging.error(f"リマインド送信中に予期せぬエラー: ID {reminder_id}, {e}")
    else:
        logging.warning(f"リマインド送信先が見つかりませんでした: ID {reminder_id}, 宛先 {target_type} {target_id}")

    if not is_recurring:
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        logging.info(f"単発リマインドID {reminder_id} をデータベースから削除しました。")
    else:
        # TODO: Implement recurring reminder rescheduling logic here
        logging.info(f"繰り返しリマインドID {reminder_id}。再スケジュール処理は未実装です。")

    conn.close()


def schedule_existing_reminders():
    """データベース内の未実行リマインドをスケジューラに登録する"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM reminders WHERE trigger_time > DATETIME('now', 'localtime') OR is_recurring = 1")
    reminders_to_schedule = cursor.fetchall()
    conn.close()

    for reminder in reminders_to_schedule:
        reminder_id = reminder['id']
        trigger_time_str = reminder['trigger_time']
        is_recurring = reminder['is_recurring']
        recurrence_rule = reminder['recurrence_rule']
        try:
            trigger_dt_naive = datetime.strptime(trigger_time_str, '%Y-%m-%d %H:%M:%S')
            trigger_dt_aware = scheduler.timezone.localize(trigger_dt_naive)

            if is_recurring:
                cron_args = {}
                if recurrence_rule:
                    parts = recurrence_rule.split(';')
                    params = {p.split('=')[0].upper(): p.split('=')[1] for p in parts if '=' in p and len(p.split('=')) == 2}
                    
                    if params.get("FREQ") == "DAILY":
                        cron_args['hour'] = params.get("BYHOUR", trigger_dt_aware.hour)
                        cron_args['minute'] = params.get("BYMINUTE", trigger_dt_aware.minute)
                    elif params.get("FREQ") == "WEEKLY":
                        day_map = {"MO":0, "TU":1, "WE":2, "TH":3, "FR":4, "SA":5, "SU":6}
                        if "BYDAY" in params:
                            cron_args['day_of_week'] = str(day_map.get(params["BYDAY"].upper()))
                        cron_args['hour'] = params.get("BYHOUR", trigger_dt_aware.hour)
                        cron_args['minute'] = params.get("BYMINUTE", trigger_dt_aware.minute)
                
                if cron_args:
                    scheduler.add_job(send_reminder, CronTrigger(**cron_args, timezone=scheduler.timezone), 
                                      args=[reminder_id], id=str(reminder_id), 
                                      misfire_grace_time=60*5, replace_existing=True)
                    logging.info(f"既存の繰り返しリマインドID {reminder_id} をスケジュール。ルール: {cron_args}")
                else:
                    if trigger_dt_aware >= datetime.now(scheduler.timezone):
                        scheduler.add_job(send_reminder, 'date', run_date=trigger_dt_aware, 
                                          args=[reminder_id], id=str(reminder_id), 
                                          misfire_grace_time=60*5, replace_existing=True)
                        logging.warning(f"既存の繰り返しリマインドID {reminder_id} のルール解析失敗。単発として {trigger_dt_aware} でスケジュール。")
            else:
                if trigger_dt_aware >= datetime.now(scheduler.timezone):
                    scheduler.add_job(send_reminder, 'date', run_date=trigger_dt_aware, 
                                      args=[reminder_id], id=str(reminder_id), 
                                      misfire_grace_time=60*5, replace_existing=True)
                    logging.info(f"既存の単発リマインドID {reminder_id} を {trigger_dt_aware} でスケジュール。")
                else:
                    logging.info(f"既存の単発リマインドID {reminder_id} ({trigger_dt_aware}) は過去のためスキップ。")

        except Exception as e:
            logging.error(f"既存リマインドID {reminder_id} のスケジュールに失敗: {e}")
            logging.error(f"  詳細: trigger_time='{trigger_time_str}', is_recurring={is_recurring}, rule='{recurrence_rule}'")

@bot.event
async def on_ready():
    logging.info(f'{bot.user} としてログインしました。')
    init_db()
    scheduler.start()
    schedule_existing_reminders()
    logging.info("スケジューラを開始し、既存のリマインドを読み込みました。")

remind_group = discord.app_commands.Group(name="remind", description="リマインダー関連のコマンド")

def parse_time_string(time_str: str, now: datetime):
    """
    ユーザーが入力した様々な形式の時刻文字列をdatetimeオブジェクトに変換する。
    繰り返しルールも解析し、次回実行時刻とルールを返す。
    戻り値: (trigger_time: datetime, is_recurring: bool, recurrence_rule_str: str or None)
    """
    time_str_lower = time_str.lower()
    trigger_time = None
    is_recurring = False
    recurrence_rule_str = None

    match = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{1,2})", time_str)
    if match:
        try:
            year, month, day, hour, minute = map(int, match.groups())
            trigger_time = datetime(year, month, day, hour, minute, tzinfo=scheduler.timezone)
            if trigger_time < now:
                 trigger_time += timedelta(days=1)
            return trigger_time, False, None
        except ValueError:
            pass

    match = re.fullmatch(r"(\d{1,2}):(\d{1,2})", time_str)
    if match:
        try:
            hour, minute = map(int, match.groups())
            trigger_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if trigger_time < now:
                trigger_time += timedelta(days=1)
            return trigger_time, False, None
        except ValueError:
            pass

    match = re.fullmatch(r"in\s+(\d+)\s+(minutes?|hours?|days?)", time_str_lower)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        delta = timedelta()
        if "minute" in unit:
            delta = timedelta(minutes=value)
        elif "hour" in unit:
            delta = timedelta(hours=value)
        elif "day" in unit:
            delta = timedelta(days=value)
        trigger_time = now + delta
        return trigger_time, False, None

    match = re.fullmatch(r"tomorrow\s+at\s+(\d{1,2}):(\d{1,2})", time_str_lower)
    if match:
        hour, minute = map(int, match.groups())
        trigger_time = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
        return trigger_time, False, None

    match = re.fullmatch(r"every\s+day\s+at\s+(\d{1,2}):(\d{1,2})", time_str_lower)
    if match:
        hour, minute = map(int, match.groups())
        trigger_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if trigger_time < now:
            trigger_time += timedelta(days=1)
        recurrence_rule_str = f"FREQ=DAILY;BYHOUR={hour};BYMINUTE={minute}"
        return trigger_time, True, recurrence_rule_str

    weekdays = {"monday": "MO", "tuesday": "TU", "wednesday": "WE", "thursday": "TH", "friday": "FR", "saturday": "SA", "sunday": "SU"}
    weekday_pattern = "|".join(weekdays.keys())
    match = re.fullmatch(rf"every\s+({weekday_pattern})\s+at\s+(\d{{1,2}}):(\d{{1,2}})", time_str_lower)
    if match:
        day_name_str = match.group(1)
        hour, minute = map(int, match.group(2,3))
        target_weekday_ical = weekdays[day_name_str]
        trigger_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        current_weekday_num = trigger_time.weekday()
        py_weekdays_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
        target_weekday_num = py_weekdays_map[target_weekday_ical]
        days_ahead = target_weekday_num - current_weekday_num
        if days_ahead < 0 or (days_ahead == 0 and trigger_time < now) :
            days_ahead += 7
        trigger_time += timedelta(days=days_ahead)
        recurrence_rule_str = f"FREQ=WEEKLY;BYDAY={target_weekday_ical};BYHOUR={hour};BYMINUTE={minute}"
        return trigger_time, True, recurrence_rule_str

    try:
        parsed_dt_naive = dateutil_parse(time_str, default=now.replace(tzinfo=None))
        if parsed_dt_naive.tzinfo is None:
            trigger_time = scheduler.timezone.localize(parsed_dt_naive)
        else:
            trigger_time = parsed_dt_naive.astimezone(scheduler.timezone)

        if trigger_time < now:
            if (parsed_dt_naive.hour == trigger_time.hour and
                parsed_dt_naive.minute == trigger_time.minute and
                parsed_dt_naive.second == trigger_time.second and
                parsed_dt_naive.date() == now.date()):
                trigger_time += timedelta(days=1)

        return trigger_time, False, None
    except (ValueError, OverflowError) as e:
        logging.debug(f"dateutil.parserでの時刻パース失敗: {time_str}, error: {e}")
        return None, False, None


@remind_group.command(name="set", description="新しいリマインドを設定します。")
@discord.app_commands.describe(
    target="リマインド先 (@me, #チャンネル名, またはユーザー/チャンネルメンション)",
    time="リマインド時刻 (例: 15:30, in 30 minutes, tomorrow at 10:00)",
    message="リマインドするメッセージ内容"
)
async def slash_set_reminder(
    interaction: discord.Interaction,
    target: str,
    time: str,
    message: str
):
    """スラッシュコマンドによるリマインド設定"""
    author = interaction.user
    guild = interaction.guild

    if not guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    target_type = None
    target_id = None
    target_display_name = target 

    if target.lower() == "@me":
        target_type = 'user'
        target_id = str(author.id)
        target_display_name = author.mention
    elif target.startswith("<#") and target.endswith(">"): 
        match = re.match(r"<#(\d+)>", target)
        if match:
            ch_id = int(match.group(1))
            ch = guild.get_channel(ch_id)
            if ch and isinstance(ch, discord.TextChannel):
                target_type = 'channel'
                target_id = str(ch.id)
                target_display_name = ch.mention
            else:
                await interaction.response.send_message(f"指定されたチャンネルメンション {target} が見つかりません。", ephemeral=True)
                return
        else:
            await interaction.response.send_message(f"無効なチャンネルメンション形式: {target}", ephemeral=True)
            return
    elif target.startswith("<@") and target.endswith(">"):
        match = re.match(r"<@!?(\d+)>", target) 
        if match:
            user_id_val = int(match.group(1))
            try:
                member = await guild.fetch_member(user_id_val)
                target_type = 'user'
                target_id = str(member.id)
                target_display_name = member.mention
            except discord.NotFound:
                try:
                    usr = await bot.fetch_user(user_id_val)
                    target_type = 'user'
                    target_id = str(usr.id)
                    target_display_name = usr.mention
                except discord.NotFound:
                    await interaction.response.send_message(f"指定されたユーザーメンション {target} が見つかりません。", ephemeral=True)
                    return
            except Exception as e:
                logging.error(f"ユーザーメンション {target} の解決エラー: {e}")
                await interaction.response.send_message("ユーザーメンションの解決中にエラー。", ephemeral=True)
                return
        else:
            await interaction.response.send_message(f"無効なユーザーメンション形式: {target}", ephemeral=True)
            return
    elif target.startswith("#"):
        ch_name = target.lstrip("#")
        found_channel = discord.utils.get(guild.text_channels, name=ch_name)
        if found_channel:
            target_type = 'channel'
            target_id = str(found_channel.id)
            target_display_name = found_channel.mention
        else:
            await interaction.response.send_message(f"チャンネル名 #{ch_name} が見つかりません。", ephemeral=True)
            return
    else:
        await interaction.response.send_message(
            f"リマインド先の指定 `{target}` が無効です。\n"
            "`@me`、`#チャンネル名`、またはユーザー/チャンネルをメンションで指定してください。",
            ephemeral=True)
        return

    if not target_type or not target_id:
        await interaction.response.send_message("リマインド先の特定に失敗しました。", ephemeral=True)
        return

    now_aware = datetime.now(scheduler.timezone)
    parsed_time_data = parse_time_string(time, now_aware)

    if not parsed_time_data or not parsed_time_data[0]:
        await interaction.response.send_message(
            f"時刻の形式が無効です: `{time}`\n"
            "例: `15:30`, `in 30 minutes`, `tomorrow at 10:00`, `every day at 9:00`",
            ephemeral=True)
        return

    trigger_datetime, is_recurring, recurrence_rule = parsed_time_data

    if trigger_datetime < now_aware:
        await interaction.response.send_message(
            f"指定された時刻 `{time}` (解決結果: {trigger_datetime.strftime('%Y-%m-%d %H:%M')}) は過去です。",
            ephemeral=True)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        command_channel_id = str(interaction.channel.id) if interaction.channel else "DM_FALLBACK"
        trigger_datetime_str = trigger_datetime.strftime('%Y-%m-%d %H:%M:%S')

        cursor.execute('''
            INSERT INTO reminders (user_id, guild_id, channel_id, target_type, target_id, message, trigger_time, is_recurring, recurrence_rule, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (str(author.id), str(guild.id), command_channel_id, target_type, target_id, message, 
              trigger_datetime_str, is_recurring, recurrence_rule, datetime.now()))
        reminder_id = cursor.lastrowid
        conn.commit()

        if is_recurring:
            cron_args = {}
            if recurrence_rule:
                parts = recurrence_rule.split(';')
                params = {p.split('=')[0].upper(): p.split('=')[1] for p in parts if '=' in p and len(p.split('=')) == 2}
                
                if params.get("FREQ") == "DAILY":
                    cron_args['hour'] = params.get("BYHOUR", trigger_datetime.hour)
                    cron_args['minute'] = params.get("BYMINUTE", trigger_datetime.minute)
                elif params.get("FREQ") == "WEEKLY":
                    day_map = {"MO":0, "TU":1, "WE":2, "TH":3, "FR":4, "SA":5, "SU":6}
                    if "BYDAY" in params:
                        cron_args['day_of_week'] = str(day_map.get(params["BYDAY"].upper()))
                    cron_args['hour'] = params.get("BYHOUR", trigger_datetime.hour)
                    cron_args['minute'] = params.get("BYMINUTE", trigger_datetime.minute)
            
            if cron_args:
                 scheduler.add_job(send_reminder, CronTrigger(**cron_args, timezone=scheduler.timezone), 
                                   args=[reminder_id], id=str(reminder_id), 
                                   misfire_grace_time=60*5, replace_existing=True)
                 logging.info(f"繰り返しリマインドID {reminder_id} をスケジュール。ルール: {cron_args}")
            else:
                scheduler.add_job(send_reminder, 'date', run_date=trigger_datetime, 
                                  args=[reminder_id], id=str(reminder_id), 
                                  misfire_grace_time=60*5, replace_existing=True)
                logging.warning(f"繰り返しルール解析失敗。リマインドID {reminder_id} を単発として {trigger_datetime} でスケジュール。Rule: {recurrence_rule}")
        else:
            scheduler.add_job(send_reminder, 'date', run_date=trigger_datetime, 
                              args=[reminder_id], id=str(reminder_id), 
                              misfire_grace_time=60*5, replace_existing=True)
            logging.info(f"単発リマインドID {reminder_id} を {trigger_datetime} でスケジュール。")

        await interaction.response.send_message(
            f"リマインドを設定しました！ (ID: `{reminder_id}`)\n"
            f"時刻: `{trigger_datetime.strftime('%Y-%m-%d %H:%M:%S %Z')}`\n"
            f"宛先: {target_display_name}\n"
            f"メッセージ: `{message}`\n"
            f"タイプ: {'繰り返し' if is_recurring else '単発'}",
            ephemeral=False 
        )

    except sqlite3.Error as e:
        logging.error(f"DBエラー (slash_set_reminder): {e}")
        await interaction.response.send_message(f"DBエラーが発生しました: {e}", ephemeral=True)
    except Exception as e:
        logging.error(f"リマインド設定中の予期せぬエラー (slash_set_reminder): {e}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"予期せぬエラーが発生しました: {e}", ephemeral=True)
        else:
            await interaction.followup.send(f"予期せぬエラーが発生しました: {e}", ephemeral=True)
    finally:
        conn.close()


@remind_group.command(name="list", description="設定されているリマインドの一覧を表示します。")
async def slash_list_reminders(interaction: discord.Interaction):
    """スラッシュコマンドによるリマインド一覧表示"""
    author_id = str(interaction.user.id)
    guild = interaction.guild

    if not guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return
    guild_id = str(guild.id)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, target_type, target_id, message, trigger_time, is_recurring, recurrence_rule
        FROM reminders
        WHERE user_id = ? AND guild_id = ? AND (trigger_time > DATETIME('now', 'localtime') OR is_recurring = 1)
        ORDER BY trigger_time ASC
    """, (author_id, guild_id))
    reminders = cursor.fetchall()
    conn.close()

    if not reminders:
        await interaction.response.send_message("設定されている有効なリマインドはありません。", ephemeral=True)
        return

    embed = discord.Embed(title=f"{interaction.user.display_name} のリマインド一覧", color=discord.Color.blue())
    output_lines = []
    for r_dict in reminders:
        dt_obj_naive = datetime.strptime(r_dict['trigger_time'], '%Y-%m-%d %H:%M:%S')
        formatted_time = dt_obj_naive.strftime('%Y/%m/%d %H:%M') + " JST"
        
        target_display = ""
        r_target_type = r_dict['target_type']
        r_target_id = r_dict['target_id']
        r_message = r_dict['message']
        r_is_recurring = r_dict['is_recurring']
        r_recurrence_rule = r_dict['recurrence_rule']
        r_id = r_dict['id']

        if r_target_type == 'user':
            if r_target_id == author_id: target_display = "@me"
            else:
                try: user = await bot.fetch_user(int(r_target_id)); target_display = user.mention
                except: target_display = f"User ID: {r_target_id}"
        elif r_target_type == 'channel':
            try: ch = await bot.fetch_channel(int(r_target_id)); target_display = ch.mention
            except: target_display = f"Channel ID: {r_target_id}"

        line = f"**ID: {r_id}** | {formatted_time} | 宛先: {target_display} | `{r_message}`"
        if r_is_recurring: line += f" ({r_recurrence_rule or '繰り返し'})"
        output_lines.append(line)

    description_text = "\n".join(output_lines)
    if len(description_text) <= 4096:
        embed.description = description_text
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        # TODO: Implement pagination for long lists
        await interaction.response.send_message("リマインド一覧が長すぎるため、現在は最初の部分のみ表示します。(この機能は未実装)", ephemeral=True)


@remind_group.command(name="delete", description="指定IDのリマインドを削除します。")
@discord.app_commands.describe(reminder_id="削除するリマインドのID")
async def slash_delete_reminder(interaction: discord.Interaction, reminder_id: int):
    """スラッシュコマンドによるリマインド削除"""
    author_id = str(interaction.user.id)
    guild_id = str(interaction.guild.id)

    if not interaction.guild:
        await interaction.response.send_message("このコマンドはサーバー内でのみ使用できます。", ephemeral=True)
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reminders WHERE id = ? AND user_id = ? AND guild_id = ?", (reminder_id, author_id, guild_id))
    to_delete = cursor.fetchone()

    if not to_delete:
        await interaction.response.send_message(f"ID `{reminder_id}` のリマインドが見つからないか、削除権限がありません。", ephemeral=True)
        conn.close()
        return

    try:
        cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        conn.commit()
        try: scheduler.remove_job(str(reminder_id))
        except Exception: pass
        await interaction.response.send_message(f"リマインド ID `{reminder_id}` を削除しました。", ephemeral=False)
    except Exception as e:
        logging.error(f"リマインド削除エラー (ID: {reminder_id}): {e}")
        await interaction.response.send_message(f"リマインド削除中にエラーが発生しました。", ephemeral=True)
    finally:
        conn.close()

bot.tree.add_command(remind_group)

if __name__ == '__main__':
    if DISCORD_BOT_TOKEN:
        bot.run(DISCORD_BOT_TOKEN)
    else:
        logging.critical("DISCORD_BOT_TOKENが設定されていません。botを起動できません。")
