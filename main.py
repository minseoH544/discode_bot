import discord
from discord.ext import commands, tasks
import json
import os
from datetime import datetime, timedelta
import pytz
from flask import Flask
from threading import Thread

app = Flask('')


@app.route('/')
def home():
    return "봇이 실행 중입니다!"


def run():
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)


def keep_alive():
    t = Thread(target=run)
    t.start()


# 환경변수 로드
try:
    from dotenv import load_dotenv
    load_dotenv()
    print("✅ .env 파일을 로드했습니다.")
except ImportError:
    print("⚠️  python-dotenv가 설치되지 않았습니다. 시스템 환경변수만 사용합니다.")

# 토큰 설정 - 환경변수에서 가져오기
TOKEN = os.getenv('DISCORD_BOT_TOKEN')
if TOKEN is None or TOKEN == "":
    print("DISCORD_BOT_TOKEN 환경변수가 설정되지 않았습니다!")
    exit(1)

# 봇 설정
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

CLASS_DATA_FILE = 'classes.json'


# 수업 데이터 로드
def load_classes():
    try:
        with open(CLASS_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# 수업 데이터 저장
def save_classes(classes):
    with open(CLASS_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(classes, f, ensure_ascii=False, indent=2)


# 전역 변수
classes = load_classes()


@bot.event
async def on_ready():
    print(f'{bot.user} 봇이 준비되었습니다!')
    check_class_reminders.start()


@bot.command(name='수업추가')
async def add_class(ctx, name=None, day=None, time=None, *, description=""):
    if not name or not day or not time:
        await ctx.send(
            "사용법: `!수업추가 <수업명> <요일> <시간> [설명]`\n예시: `!수업추가 \"파이썬\" 월 14:30`")
        return

    guild_id = str(ctx.guild.id)
    channel_id = ctx.channel.id

    if guild_id not in classes:
        classes[guild_id] = {}

    days = {'월': 0, '화': 1, '수': 2, '목': 3, '금': 4, '토': 5, '일': 6} #요일을 숫자로 저장

    if day not in days:
        await ctx.send("올바른 요일을 입력해주세요. (월, 화, 수, 목, 금, 토, 일)")
        return

    #24시간 형식 확인
    try:
        datetime.strptime(time, '%H:%M')
    except ValueError:
        await ctx.send("시간은 HH:MM 형식으로 입력해주세요. (예: 14:30)")
        return

    class_info = {
        'name': name,
        'day': days[day],
        'time': time,
        'description': description,
        'channel_id': channel_id
    }

    class_key = f"{name}_{day}_{time}"
    classes[guild_id][class_key] = class_info
    save_classes(classes)

    embed = discord.Embed(title="✅ 수업이 추가되었습니다!", color=0x00ff00)
    embed.add_field(name="수업명", value=name, inline=True)
    embed.add_field(name="요일", value=day, inline=True)
    embed.add_field(name="시간", value=time, inline=True)
    if description:
        embed.add_field(name="설명", value=description, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='수업목록')
async def list_classes(ctx):
    guild_id = str(ctx.guild.id)

    if guild_id not in classes or not classes[guild_id]:
        await ctx.send("📚 등록된 수업이 없습니다.")
        return

    embed = discord.Embed(title="📚 등록된 수업 목록", color=0x0099ff)

    days_kr = ['월', '화', '수', '목', '금', '토', '일']

    for class_key, class_info in classes[guild_id].items():
        day_name = days_kr[class_info['day']]
        field_name = f"{class_info['name']}"
        field_value = f"{day_name} {class_info['time']}"
        if class_info['description']:
            field_value += f"\n📝 {class_info['description']}"

        embed.add_field(name=field_name, value=field_value, inline=False)

    await ctx.send(embed=embed)


@bot.command(name='수업삭제')
async def remove_class(ctx, *, class_name=None):
    if not class_name:
        await ctx.send("사용법: `!수업삭제 <수업명>`")
        return

    guild_id = str(ctx.guild.id)

    if guild_id not in classes:
        await ctx.send("📚 등록된 수업이 없습니다.")
        return

    removed_classes = []
    for class_key in list(classes[guild_id].keys()):
        if class_name.lower() in classes[guild_id][class_key]['name'].lower():
            removed_classes.append(classes[guild_id][class_key]['name'])
            del classes[guild_id][class_key]

    if removed_classes:
        save_classes(classes)
        embed = discord.Embed(title="🗑️ 수업이 삭제되었습니다!",
                              description="\n".join(removed_classes),
                              color=0xff0000)
        await ctx.send(embed=embed)
    else:
        await ctx.send(f"'{class_name}'과(와) 일치하는 수업을 찾을 수 없습니다.")


@tasks.loop(minutes=1)
async def check_class_reminders():
    try:
        now = datetime.now(pytz.timezone('Asia/Seoul'))
        current_weekday = now.weekday()

        for guild_id, guild_classes in classes.items():
            for class_key, class_info in guild_classes.items():
                if class_info['day'] != current_weekday: #오늘인지 확인
                    continue

                class_time = datetime.strptime(class_info['time'],
                                               '%H:%M').time()
                class_datetime = datetime.combine(now.date(), class_time)
                class_datetime = pytz.timezone('Asia/Seoul').localize(
                    class_datetime)

                reminder_time = class_datetime - timedelta(minutes=10) #수업시작시간 10분 전 계산

                if abs((now - reminder_time).total_seconds()) <= 30: #현재시각과 알림시각 일치하는지 확인
                    try:
                        channel = bot.get_channel(class_info['channel_id'])
                        if channel and isinstance(
                                channel,
                            (discord.TextChannel, discord.VoiceChannel,
                             discord.StageChannel, discord.Thread)):
                            embed = discord.Embed(
                                title="🔔 수업 알림",
                                description=
                                f"**{class_info['name']}** 수업이 10분 후에 시작됩니다!",
                                color=0xffaa00,
                                timestamp=now)
                            embed.add_field(name="수업 시간",
                                            value=class_info['time'],
                                            inline=True)
                            if class_info['description']:
                                embed.add_field(
                                    name="수업 정보",
                                    value=class_info['description'],
                                    inline=False)

                            embed.set_footer(text="수업 준비를 해주세요! 📚")

                            await channel.send("@everyone", embed=embed)
                            print(f"알림 전송: {class_info['name']} - {guild_id}")
                        else:
                            print(
                                f"채널을 찾을 수 없거나 메시지를 보낼 수 없는 채널: {class_info['channel_id']}"
                            )
                    except Exception as e:
                        print(f"알림 전송 오류: {e}")
    except Exception as e:
        print(f"알림 확인 중 오류 발생: {e}")

@bot.command(name='도움말')
async def help_command(ctx):
    embed = discord.Embed(title="📖 수업 알림 봇 사용법",
                          description="수업 시작 10분 전에 자동으로 알림을 보내는 봇입니다.",
                          color=0x7289da)

    embed.add_field(
        name="!수업추가 <수업명> <요일> <시간> [설명]",
        value="새로운 수업을 추가합니다.\n예: `!수업추가 \"파이썬 프로그래밍\" 월 14:30 컴퓨터실A`",
        inline=False)

    embed.add_field(name="!수업목록", value="등록된 모든 수업을 확인합니다.", inline=False)

    embed.add_field(name="!수업삭제 <수업명>",
                    value="수업을 삭제합니다.\n예: `!수업삭제 파이썬`",
                    inline=False)

    embed.add_field(name="!도움말", value="이 도움말을 표시합니다.", inline=False)

    await ctx.send(embed=embed)



@bot.event
async def on_command_error(ctx, error): #에러 발생 시
    if isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ 존재하지 않는 명령어입니다. `!도움말`을 입력해서 사용법을 확인해주세요.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ 필수 매개변수가 누락되었습니다. `!도움말`을 참고해주세요.")
    else:
        await ctx.send(f"❌ 오류가 발생했습니다: {str(error)}")
        print(f"Error: {error}")


# 봇 실행
if __name__ == "__main__":
    keep_alive()
    bot.run(TOKEN)
