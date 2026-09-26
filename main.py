import asyncio
import json
import os
import random
import re
from datetime import date, datetime
from html import escape

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandObject, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputPollOption,
    InputTextMessageContent,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    FSInputFile,
)
from dotenv import load_dotenv

# ======================================================================================
#  SOZLAMALAR
# ======================================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def get_int_env(name: str, default: int) -> int:
    """Return an integer environment value without crashing on bad configuration."""
    raw_value = os.getenv(name, str(default)).strip()
    try:
        return int(raw_value)
    except ValueError:
        print(f"Ogohlantirish: {name} noto'g'ri berilgan, {default} ishlatiladi.")
        return default

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env fayliga BOT_TOKEN ni kiriting.")

ADMIN_ID = get_int_env("ADMIN_ID", 0)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "").lstrip("@")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "GoldCinema_Kanal").lstrip("@")
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_NAME = os.getenv("CARD_NAME", "").strip()

# Kuniga nechta kino bepul ko'rish mumkinligi (Premium bo'lmagan foydalanuvchilar uchun)
DAILY_FREE_LIMIT = max(0, get_int_env("DAILY_FREE_LIMIT", 3))

PREMIUM_USERS = [
    int(user_id)
    for user_id in re.findall(
        r"[0-9]+",
        os.getenv("PREMIUM_USERS", os.getenv("PREMIUM_USERs", "")),
    )
]
PREMIUM_USERS_CONFIGURED = "PREMIUM_USERS" in os.environ or "PREMIUM_USERs" in os.environ
ALL_USERS = set()          # Botdan foydalangan barcha foydalanuvchilar ID lari
USER_INFO = {}              # {user_id: {"name": str, "username": str, "joined": str}}

FAVORITES: dict[int, set[str]] = {}     # {user_id: {code, code, ...}}
VIEWS: dict[int, int] = {}              # {user_id: nechta kino ko'rgani (umumiy)}
DAILY_VIEWS: dict[int, dict] = {}       # {user_id: {"date": "YYYY-MM-DD", "count": int}}
REFERRALS: dict[int, set[int]] = {}     # {referrer_id: {taklif qilinganlar}}
REFERRED_BY: dict[int, int] = {}        # {user_id: kim taklif qilgani}

CURRENT_PREMIERE: str | None = None     # Hozirgi premyera kino kodi
DATA_FILE = os.path.join(BASE_DIR, "gold_cinema_data.json")
USERS_DATA_FILE = os.path.join(BASE_DIR, "users_database.json")

BOT_START_TIME = datetime.now()
BOT_USERNAME = ""  # main() ichida to'ldiriladi

session = AiohttpSession(timeout=60)
bot = Bot(token=BOT_TOKEN, session=session)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


def premium_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🗓 1 hafta — 15 000 so'm", callback_data="premium_plan:week")],
            [InlineKeyboardButton(text="📅 1 oy — 35 000 so'm", callback_data="premium_plan:month")],
            [InlineKeyboardButton(text="🎁 3 oy — 90 000 so'm", callback_data="premium_plan:quarter")],
            [InlineKeyboardButton(text="👑 1 yil — 300 000 so'm", callback_data="premium_plan:year")],
        ]
    )


class AddMovie(StatesGroup):
    name = State()
    til = State()
    sifat = State()
    yil = State()
    janr = State()
    davlat = State()
    davomiyligi = State()
    file_id = State()
    is_premium = State()


class ReplaceMovieFile(StatesGroup):
    code = State()


class DeleteMovie(StatesGroup):
    code = State()


class EditMovie(StatesGroup):
    code = State()
    field = State()
    value = State()


class AdminPremium(StatesGroup):
    user_id = State()


class AdminPremiere(StatesGroup):
    code = State()


class BroadcastState(StatesGroup):
    message = State()


class MovieRequestState(StatesGroup):
    waiting = State()


class AdminPollState(StatesGroup):
    waiting = State()


class PremiumPaymentState(StatesGroup):
    waiting_receipt = State()


# ======================================================================================
#  KINOLAR BAZASI
# ======================================================================================

MOVIES_DATABASE = {
"1": {
        "file_id": "BAACAgIAAxkBAAMiaovw81ufq828W5Uug8LSvAVi_PgAAvpvAAKtEuBKyZ2zMf7IOs49BA",
        "name": "Changalzordagi ajal",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2025",
        "janr": "tarjima qo'rqinchli",
        "davlat": "Britaniya, Tailand va Daniya kinostudiyalari tomonidan hamkorlikda ishlab chiqarilgan",
        "davomiyligi": "1 soat 27 minut",
        "is_premium": False,
    },
    "2": {
        "file_id": "BAACAgEAAxkBAAIGwmqg4HiGLfNoK2hR48wPs6DkU6l5AAKfAgACIcQ5R2bk0KgSv1LUPQQ",
        "name": "Texasdagi qonli qirg'in",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2024",
        "janr": "tarjima qo'rqinchli",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 30 minut",
        "is_premium": False,
    },
    "3": {
        "file_id": "BAACAgEAAxkBAAICPmqMbNWi0yQw3BtUZMe4hlrQgyT_AAKmAwACothRRMidliKEFjywPQQ",
        "name": "Yashil maskan",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "1999",
        "janr": "Drama, mistika",
        "davlat": "AQSH",
        "davomiyligi": "3 soat 15 minut",
        "is_premium": False,
    },
    "4": {
        "file_id": "BAACAgQAAxkBAAICy2qNYByn44-AczRcn6pXwA6HuFhqAALuFQACaLdgURYfYOuh3e8pPQQ",
        "name": "Oltin to'qmoq",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2009",
        "janr": "Komediya, jangari Sarguzasht",
        "davlat": "Yaponiya",
        "davomiyligi": "1 soat 44 minut",
        "is_premium": False,
    },
    "5": {
        "file_id": "BAACAgIAAxkBAAIDa2qNdMltNSLlqMa_-yfX1GYBp1Z2AALSWgACmjlpSQkITks366C-PQQ",
        "name": "O'lim ovozi",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2024",
        "janr": "tarjima qo'rqinchli",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 28 minut",
        "is_premium": False,
    },
    "6": {
        "file_id": "BAACAgQAAxkBAAIDb2qNqm4StSOh7zTpqVmDGZMGW6QrAALqCQACo2aJUxF0l3u5t9uqPQQ",
        "name": "Qotilning rafiqasi tansoqchisi",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2021",
        "janr": "tarjima qo'rqinchli",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 30 minut",
        "is_premium": False,
    },
    "7": {
        "file_id": "BAACAgIAAxkBAAIDpGqNzzw19vL5tNidgib0Pv07XUi5AAJOpAACCdpoS8mE8yxDAXA4PQQ",
        "name": "O'zaro qizlar o'rtasida",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2016",
        "janr": "Romantika, drama",
        "davlat": "italiya",
        "davomiyligi": "1 soat 32 minut",
        "is_premium": False,
    },
    "8": {
        "file_id": "BAACAgIAAxkBAAIF2WqbxuAuZQsILSXB9wT8A9YKyH_YAAI-qgACTj6hSIRpqnTl6l4XPQQ",
        "name": "QO'RQINCHLI SAHRO",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2015",
        "janr": " Qo'rqinchli, dramma ",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 25 minut",
        "is_premium": False,
    },
    "9": {
        "file_id": "BAACAgIAAxkBAAIFnWqUdTyk-mNxlYwCcOnQNM1XpZWdAAJlqgACTj6hSLaS-Og5mK02PQQ",
        "name": "Iblisga o`lja",
        "til": "O'zbek tilida",
        "sifat": "7200p",
        "yil": "2022",
        "janr": "Qo'rqinchli, triller",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 29 minut",
        "is_premium": False,
    },
    "10": {
        "file_id": "BAACAgEAAxkBAAIDcWqNrVFrgdkTm-q8oeT8cjTyean3AALOBAAC-sj4RAzcweghM14RPQQ",
        "name": "Uch qahramon",
        "til": "O'zbek tilida",
        "sifat": "1080p ",
        "yil": "2025",
        "janr": "Jangari, Dramma",
        "davlat": "AQSH",
        "davomiyligi": "2 soat 21 minut",
        "is_premium": False,
    },
    "11": {
        "file_id": "BAACAgUAAxkBAAIDc2qNraWEO3AAAWlHAceRVmRbhpiHjQAC7g8AAlG7oVRAfHnNHskHkz0E",
        "name": "Noto'g'ri burilish: 2 qism",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": " 2008 ",
        "janr": "Qo'rqinchli Sagruzasht",
        "davlat": " Aqsh",
        "davomiyligi": "1 soat 36 minut",
        "is_premium": False,
    },
    "12": {
        "file_id": "BAACAgUAAxkBAAIDdGqNrnfdikFn4tDI8QSWfuCiQfoGAALyDwACUbuhVIrjAbbO2TvSPQQ",
        "name": "Noto'g'ri burilish: 3 qism",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2009",
        "janr": "Qo'rqinchli, sarguzasht",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 32 minut",
        "is_premium": False,
    },
    "13": {
        "file_id": "BAACAgIAAxkBAAIFu2qbwsxSMelY0mG_kVE_cuu3JxnkAAJ6qQACQzvYSJAN9_dmsNAbPQQ",
        "name": "Ajdar nayzasi",
        "til": "O'zbek tilida",
        "sifat": "480p",
        "yil": "2008",
        "janr": "Multfilm, sarguzasht",
        "davlat": "AQSH, Germaniya, Hindiston",
        "davomiyligi": "1 soat 31 minut",
        "is_premium": False,
    },
    "14": {
        "file_id": "BAACAgIAAxkBAAIFwWqbxXf8JOXZFQSM4rlwPPonp6O-AAJDmwACBobhSANYpeMwg_99PQQ",
        "name": "Maymunlar saltanati",
        "til": "O'zbek tilida",
        "sifat": "480p",
        "yil": "1999",
        "janr": "multfilm, sarguzasht, ",
        "davlat": "Fransiya",
        "davomiyligi": "1 soat 12 minut",
        "is_premium": False,
    },
    "15": {
        "file_id": "BAACAgIAAxkBAAIG0GqFzidURAPi-cY9sI6mQyMkyKV3AALnIAACyWSwUiCatVZuzQdEPQQ",
        "name": "Sidjin 1 Qismi",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2014",
        "janr": "detektiv, drama",
        "davlat": "AQSH",
        "davomiyligi": "2 soat 56 minut",
        "is_premium": False,
    },
    "16": {
        "file_id": "BAACAgIAAxkBAAICjWptfbcZpvvHIYR92dfV9ZgdM3UjAAL6bwACrRLgSofr7BQLsU3GPQQ",
        "name": "Chumoli odam",
        "til": "O'zbek tilida",
        "sifat": "720p ",
        "yil": "2015",
        "janr": "fantastika, triller",
        "davlat": "AQSH",
        "davomiyligi": "1 soat 56 minut",
        "is_premium": False,
    },
    "17": {
        "file_id": "BAACAgQAAxkBAAIG6Gqm3EvfZmsUAia9Ud7GnyjJSqyvAAJTGQACO_hgUAABUlFY9cN0Az0E",
        "name": "Faun Labirinti",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2006 ",
        "janr": "Fantaziya Drama",
        "davlat": "Meksika",
        "davomiyligi": "1 soat 58 minut",
        "is_premium": False,
    },
    "18": {
        "file_id": "BAACAgIAAxkBAAIG6mqm4WdN9VqW31Z_qTmAtoOFoEzzAAKHqQAChUY5Sej4DmeSwBJrPQQ",
        "name": " O'rgimchak Zinaning sarguzashtlari",
        "til": "O'zbek tilida",
        "sifat": "720p", 
        "yil": "1996",
        "janr": "Multfilm,Animatsiya",
        "davlat": "Fransiya",
        "davomiyligi": "21 soat 31 minut",
        "is_premium": False,
    },
    "19": {
        "file_id": "BAACAgQAAxkBAAIG7Gqm7aPiSXKYy3Pk9PLxIR3QxQABmQACcCMAAog_gVMkIp7Lbq-wRD0E",
        "name": " To'rt devor orasida",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2025",
        "janr": "Drama, Triller",
        "davlat": "Janubiy Koreya",
        "davomiyligi": "1 soat 58 minut",
        "is_premium": False,
        
        
        "20":{
            "file_id": "BAACAgQAAxkBAAIHVGqvsnZTBzvr7ePv9aPZqJjLOwRiAAJGIQAC-gyAUWvwB148Man5PQQ",
                    "name": "Li Kronning Mumiyosi",
                    "til": "O'zbek tilida",
                    "sifat": "1080p",
                    "yil": "2025",
                    "janr": "Qo'rqinchli, Sarguzasht",
                    "davlat": " Irlandiya Va Ispaniya.",
                    "davomiyligi": "2 soat 15 daqiqa",
                    "is_premium": False,
        }
            
    },
    
   
}

for _movie in MOVIES_DATABASE.values():
    _movie.setdefault("likes", set())
    _movie.setdefault("dislikes", set())
    _movie.setdefault("is_premiere", False)
    _movie.setdefault("trailer_file_id", None)


def capitalize_movie_text(value: str) -> str:
    """Har bir so'z bosh harfini kattalashtiradi va apostroflarni saqlaydi."""
    words = []
    for word in str(value).split(" "):
        match = re.search(r"[A-Za-zА-Яа-яЎўҚқҒғҲҳ]", word)
        if match:
            index = match.start()
            word = word[:index] + word[index].upper() + word[index + 1:]
        words.append(word)
    return " ".join(words)


def normalize_movie_descriptions() -> None:
    """Barcha kino nomi va tavsiflarini bir xil bosh harf formatiga o'tkazadi."""
    fields = ("name", "til", "sifat", "yil", "janr", "davlat", "davomiyligi")
    for movie in MOVIES_DATABASE.values():
        for field in fields:
            if field in movie and movie[field] is not None:
                movie[field] = capitalize_movie_text(str(movie[field]).strip())


def normalize_movie_schema() -> None:
    """Normalize legacy movie keys so all records use the same field names."""
    for movie in MOVIES_DATABASE.values():
        if "Janr" in movie and "janr" not in movie:
            movie["janr"] = movie.pop("Janr")


def save_data() -> None:
    """Kinolar, foydalanuvchilar va reytinglarni restartdan keyin ham saqlaydi."""
    movies_data = {}
    for code, movie in MOVIES_DATABASE.items():
        movie_data = dict(movie)
        movie_data.pop("likes", None)
        movie_data.pop("dislikes", None)
        movies_data[code] = movie_data
    data = {
        "movies": movies_data,
        "premium_users": list(dict.fromkeys(PREMIUM_USERS)),
        "all_users": list(ALL_USERS),
        "user_info": {str(k): v for k, v in USER_INFO.items()},
        "favorites": {str(k): list(v) for k, v in FAVORITES.items()},
        "views": {str(k): v for k, v in VIEWS.items()},
        "daily_views": {str(k): v for k, v in DAILY_VIEWS.items()},
        "referrals": {str(k): list(v) for k, v in REFERRALS.items()},
        "referred_by": {str(k): v for k, v in REFERRED_BY.items()},
        "current_premiere": CURRENT_PREMIERE,
        "ratings": {
            code: {"likes": list(movie["likes"]), "dislikes": list(movie["dislikes"])}
            for code, movie in MOVIES_DATABASE.items()
        },
    }
    users_data = [
        {
            "id": user_id,
            "name": info.get("name", "Noma'lum"),
            "username": info.get("username", "Mavjud emas"),
            "phone": info.get("phone", "Mavjud emas"),
            "joined": info.get("joined", "Noma'lum"),
            "premium": user_id in PREMIUM_USERS,
        }
        for user_id, info in USER_INFO.items()
    ]
    temporary_file = f"{DATA_FILE}.tmp"
    users_temporary_file = f"{USERS_DATA_FILE}.tmp"
    try:
        with open(temporary_file, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(temporary_file, DATA_FILE)
        with open(users_temporary_file, "w", encoding="utf-8") as file:
            json.dump(users_data, file, ensure_ascii=False, indent=2)
        os.replace(users_temporary_file, USERS_DATA_FILE)
    except OSError as error:
        print(f"Ma'lumotlarni saqlashda xatolik: {error}")


def load_data() -> None:
    """Oldingi sessiya ma'lumotlarini yuklaydi; buzilgan fayl botni to'xtatmaydi."""
    global CURRENT_PREMIERE
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, encoding="utf-8") as file:
            data = json.load(file)
        if not PREMIUM_USERS_CONFIGURED:
            PREMIUM_USERS[:] = list(dict.fromkeys(
                PREMIUM_USERS + [int(user_id) for user_id in data.get("premium_users", [])]
            ))
        ALL_USERS.update(int(user_id) for user_id in data.get("all_users", []))
        USER_INFO.update({int(k): v for k, v in data.get("user_info", {}).items()})
        FAVORITES.update({int(k): set(v) for k, v in data.get("favorites", {}).items()})
        VIEWS.update({int(k): int(v) for k, v in data.get("views", {}).items()})
        DAILY_VIEWS.update({int(k): v for k, v in data.get("daily_views", {}).items()})
        REFERRALS.update({int(k): set(v) for k, v in data.get("referrals", {}).items()})
        REFERRED_BY.update({int(k): int(v) for k, v in data.get("referred_by", {}).items()})
        CURRENT_PREMIERE = data.get("current_premiere")
        for code, movie in data.get("movies", {}).items():
            if isinstance(movie, dict):
                MOVIES_DATABASE[str(code)] = movie
                if "Janr" in movie and "janr" not in movie:
                    movie["janr"] = movie.pop("Janr")
                MOVIES_DATABASE[str(code)].setdefault("likes", set())
                MOVIES_DATABASE[str(code)].setdefault("dislikes", set())
                MOVIES_DATABASE[str(code)].setdefault("is_premiere", False)
                MOVIES_DATABASE[str(code)].setdefault("trailer_file_id", None)
        for code, ratings in data.get("ratings", {}).items():
            if code in MOVIES_DATABASE:
                MOVIES_DATABASE[code]["likes"] = set(ratings.get("likes", []))
                MOVIES_DATABASE[code]["dislikes"] = set(ratings.get("dislikes", []))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"Saqlangan ma'lumotlarni yuklashda xatolik: {error}")


load_data()
normalize_movie_schema()
normalize_movie_descriptions()
save_data()


# ======================================================================================
#  YORDAMCHI FUNKSIYALAR
# ======================================================================================

DIVIDER = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈┈"


def register_user(user) -> bool:
    """Foydalanuvchini ro'yxatdan o'tkazadi. Agar u YANGI bo'lsa True qaytaradi."""
    if not user:
        return False
    is_new = user.id not in ALL_USERS
    ALL_USERS.add(user.id)
    if user.id not in USER_INFO:
        USER_INFO[user.id] = {
            "name": user.full_name or "Noma'lum",
            "username": f"@{user.username}" if user.username else "Mavjud emas",
            "phone": "Mavjud emas",
            "joined": datetime.now().strftime("%d.%m.%Y | %H:%M"),
        }
    save_data()
    return is_new


def get_callback_message(call: CallbackQuery) -> Message | None:
    """Callback xabarini faqat tahrirlash mumkin bo'lsa qaytaradi."""
    return call.message if isinstance(call.message, Message) else None


def format_duration(davomiyligi: str) -> str:
    match = re.match(r"\s*(\d+)\s*soat\s*(\d+)\s*minut", davomiyligi)
    if match:
        return f"{match.group(1)} soat {match.group(2)} daqiqa"
    return davomiyligi.strip()


def build_caption(code: str, movie: dict) -> str:
    premium_badge = "💎 <b>PREMIUM KINO</b>\n" if movie.get("is_premium") else ""
    premiere_badge = "🎬 <b>PREMYERA!</b>\n" if movie.get("is_premiere") else ""
    lines = [
        f"{premiere_badge}{premium_badge}🎬 <b>{escape(str(movie['name']))}</b>",
        DIVIDER,
        f"🗣  <b>Tili:</b> {escape(str(movie['til']))}",
        f"📼  <b>Sifati:</b> {escape(str(movie['sifat']))}",
        f"📅  <b>Yili:</b> {escape(str(movie['yil']))}",
        f"🎭  <b>Janri:</b> {escape(str(movie['janr']))}",
        f"🌍  <b>Davlat:</b> {escape(str(movie['davlat']))}",
        f"⏳  <b>Davomiyligi:</b> {escape(format_duration(str(movie['davomiyligi'])))}",
        DIVIDER,
        f"🔎 <b>Kino kodi:</b> <code>{code}</code>",
        "",
        "✨ Yoqdimi? Baho bering va do'stlaringizga ulashing!",
        f"📢 <b>Kanalimiz:</b> @{escape(CHANNEL_USERNAME)}",
    ]
    return "\n".join(lines)


def has_premium_access(user_id: int | None) -> bool:
    return user_id is not None and (user_id == ADMIN_ID or user_id in PREMIUM_USERS)


def today_str() -> str:
    return date.today().isoformat()


def get_remaining_free_views(user_id: int | None) -> int:
    """Premium bo'lsa -1 (cheksiz) qaytaradi, aks holda qolgan bepul ko'rishlar sonini."""
    if user_id is None or has_premium_access(user_id):
        return -1
    record = DAILY_VIEWS.get(user_id)
    if not record or record.get("date") != today_str():
        return DAILY_FREE_LIMIT
    return max(0, DAILY_FREE_LIMIT - int(record.get("count", 0)))


def register_daily_view(user_id: int) -> None:
    if has_premium_access(user_id):
        return
    record = DAILY_VIEWS.setdefault(user_id, {"date": today_str(), "count": 0})
    if record.get("date") != today_str():
        record["date"] = today_str()
        record["count"] = 0
    record["count"] = int(record.get("count", 0)) + 1


def premium_offer_text() -> str:
    return (
        "💎 <b>Gold Cinema Premium</b>\n\n"
        f"Bepul foydalanuvchilar kuniga <b>{DAILY_FREE_LIMIT} ta</b> kino ko'rishi mumkin.\n"
        "Premium bilan esa cheklovsiz, istalgan qadar kino tomosha qilasiz!\n\n"
        "👇 O'zingizga mos tarifni tanlang:"
    )


def build_movie_keyboard(code: str, movie: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    likes = len(movie["likes"])
    dislikes = len(movie["dislikes"])
    is_fav = user_id is not None and code in FAVORITES.get(user_id, set())
    fav_text = "💛 Saqlangan" if is_fav else "⭐ Saqlash"

    keyboard = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"like:{code}"),
            InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"dislike:{code}"),
        ],
        [
            InlineKeyboardButton(text=fav_text, callback_data=f"fav:{code}"),
            InlineKeyboardButton(text="🔄 Boshqa kino", callback_data="menu_rand"),
        ],
        [InlineKeyboardButton(text="🧭 Bosh menyu", callback_data="menu_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def get_admin_keyboard():
    return build_admin_reply_keyboard()


def build_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="👑 Admin panel"), KeyboardButton(text="👤 Foydalanuvchi paneli")],
            [KeyboardButton(text="👥 Foydalanuvchilar ro'yxati"), KeyboardButton(text="📊 Bot statistikasi")],
            [KeyboardButton(text="💎 Premium users"), KeyboardButton(text="📥 Bazani yuklab olish")],
            [KeyboardButton(text="➕ Kino qo'shish"), KeyboardButton(text="✏️ Kino tahrirlash")],
            [KeyboardButton(text="🗑 Kino o'chirish"), KeyboardButton(text="🎬 Premyera sozlash")],
            [KeyboardButton(text="👑 Premium berish/olish"), KeyboardButton(text="📚 Kino ro'yxati")],
            [KeyboardButton(text="📢 Xabar yuborish"), KeyboardButton(text="🗳 So'rovnoma yuborish")],
            [KeyboardButton(text="💾 Ma'lumotlarni saqlash")],
        ],
        resize_keyboard=True,
    )


def build_user_reply_keyboard() -> ReplyKeyboardMarkup:
    keyboard = []
    if CURRENT_PREMIERE and CURRENT_PREMIERE in MOVIES_DATABASE:
        keyboard.append([KeyboardButton(text="🎬 PREMYERA KINO")])
    keyboard += [
        [KeyboardButton(text="🎲 Tasodifiy kino"), KeyboardButton(text="📅 Kunning kinosi")],
        [KeyboardButton(text="🔥 TOP kinolar"), KeyboardButton(text="🎯 Menga mos kino")],
        [KeyboardButton(text="⭐ Sevimlilarim"), KeyboardButton(text="📊 Statistikam")],
        [KeyboardButton(text="📝 Kino so'rash"), KeyboardButton(text="🤝 Do'stni taklif qilish")],
        [KeyboardButton(text="💎 Premium"), KeyboardButton(text="🔎 Qidirish yordami")],
    ]
    if ADMIN_USERNAME:
        keyboard.append([KeyboardButton(text="📞 Admin bilan bog'lanish")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Oddiy foydalanuvchi uchun bosh menyudagi foydali inline tugmalar."""
    keyboard = []

    if CURRENT_PREMIERE and CURRENT_PREMIERE in MOVIES_DATABASE:
        keyboard.append([InlineKeyboardButton(text="🎬 PREMYERA KINO", callback_data="menu_premiere")])

    keyboard += [
        [
            InlineKeyboardButton(text="🎲 Tasodifiy kino", callback_data="menu_rand"),
            InlineKeyboardButton(text="📅 Kunning kinosi", callback_data="menu_daily"),
        ],
        [
            InlineKeyboardButton(text="🔥 TOP kinolar", callback_data="menu_top"),
            InlineKeyboardButton(text="🎯 Menga mos kino", callback_data="menu_recommend"),
        ],
        [
            InlineKeyboardButton(text="⭐ Sevimlilarim", callback_data="menu_favorites"),
            InlineKeyboardButton(text="📊 Statistikam", callback_data="menu_stats"),
        ],
        [
            InlineKeyboardButton(text="📝 Kino so'rash", callback_data="menu_request"),
            InlineKeyboardButton(text="🤝 Do'stni taklif qilish", callback_data="menu_referral"),
        ],
        [
            InlineKeyboardButton(text="💎 Premium", callback_data="premium_info"),
            InlineKeyboardButton(text="🔎 Qidirish yordami", callback_data="menu_search_help"),
        ],
    ]
    if ADMIN_USERNAME:
        keyboard.append(
            [InlineKeyboardButton(text="📞 Admin bilan bog'lanish", url=f"https://t.me/{ADMIN_USERNAME}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_panel_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton(text="👥 Foydalanuvchilar ro'yxati", callback_data="admin_users"),
            InlineKeyboardButton(text="📊 Bot statistikasi", callback_data="admin_stats"),
        ],
        [
            InlineKeyboardButton(text="➕ Kino qo'shish", callback_data="admin_add"),
            InlineKeyboardButton(text="✏️ Tahrirlash", callback_data="admin_edit"),
        ],
        [
            InlineKeyboardButton(text="🗑 Kino o'chirish", callback_data="admin_delete"),
            InlineKeyboardButton(text="🎬 Premyera", callback_data="admin_premiere"),
        ],
        [
            InlineKeyboardButton(text="👑 Premium berish/olish", callback_data="admin_premium_manage"),
            InlineKeyboardButton(text="📚 Kino ro'yxati", callback_data="admin_movies"),
        ],
        [
            InlineKeyboardButton(text="📢 Xabar yuborish (Broadcast)", callback_data="admin_broadcast"),
            InlineKeyboardButton(text="🗳 So'rovnoma yuborish", callback_data="admin_poll"),
        ],
        [
            InlineKeyboardButton(text="💎 Premium users", callback_data="admin_premium"),
            InlineKeyboardButton(text="📥 Bazani yuklab olish", callback_data="admin_export"),
        ],
        [
            InlineKeyboardButton(text="💾 Saqlash", callback_data="admin_save"),
            InlineKeyboardButton(text="👤 User paneli", callback_data="user_panel"),
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def find_movie_matches(query: str) -> dict:
    query = query.strip().lower()
    if not query:
        return {}
    return {
        code: m
        for code, m in MOVIES_DATABASE.items()
        if query in str(m.get("name", "")).lower()
        or query in str(m.get("janr", "")).lower()
    }


def movie_code_sort_key(code: str) -> tuple[int, int | str]:
    """Sort numeric movie codes first while supporting custom codes safely."""
    return (0, int(code)) if str(code).isdigit() else (1, str(code).lower())


def build_results_text(title: str, matches: dict) -> str:
    text = f"{title}\n\n"
    for code, movie in matches.items():
        text += f"🎬 <b>{movie['name']}</b> — kodi: <code>{code}</code> ({movie['yil']})\n"
    text += "\n👇 <i>Kino ko'rish uchun uning kodini chatga yuboring!</i>"
    return text


async def broadcast_text(text: str, reply_markup: InlineKeyboardMarkup | None = None) -> tuple[int, int]:
    """Barcha foydalanuvchilarga xabar yuboradi. (muvaffaqiyatli, xato) sonini qaytaradi."""
    ok, fail = 0, 0
    for user_id in list(ALL_USERS):
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=reply_markup)
            ok += 1
        except (TelegramBadRequest, TelegramForbiddenError):
            fail += 1
        await asyncio.sleep(0.05)  # Telegram flood-limitiga tushib qolmaslik uchun
    return ok, fail


# ======================================================================================
#  START, ADMIN PANEL VA REFERAL HANDLERLARI
# ======================================================================================

@dp.message(CommandStart(deep_link=True))
@dp.message(CommandStart())
async def start_cmd(message: Message, command: CommandObject | None = None):
    if not message.from_user:
        return
    is_new = register_user(message.from_user)

    # --- Referal linkni tekshirish (masalan: https://t.me/bot?start=ref123456) ---
    if is_new and command and command.args and command.args.startswith("ref"):
        try:
            referrer_id = int(command.args[3:])
        except ValueError:
            referrer_id = None
        if referrer_id and referrer_id != message.from_user.id and message.from_user.id not in REFERRED_BY:
            REFERRED_BY[message.from_user.id] = referrer_id
            REFERRALS.setdefault(referrer_id, set()).add(message.from_user.id)
            save_data()
            count = len(REFERRALS[referrer_id])
            try:
                await bot.send_message(
                    referrer_id,
                    f"🤝 Sizning taklifingiz bilan yangi foydalanuvchi qo'shildi!\n"
                    f"Jami taklif qilinganlar: <b>{count}</b> ta.",
                    parse_mode="HTML",
                )
            except TelegramBadRequest:
                pass
            if count == 3 and referrer_id not in PREMIUM_USERS:
                PREMIUM_USERS.append(referrer_id)
                save_data()
                try:
                    await bot.send_message(
                        referrer_id,
                        "🎉 Tabriklaymiz! 3 ta do'stingizni taklif qildingiz va 💎 Premium maqomga ega bo'ldingiz!",
                    )
                except TelegramBadRequest:
                    pass

    if message.from_user.id == ADMIN_ID:
        await message.answer(
            f"👑 <b>Xush kelibsiz, Admin {message.from_user.full_name}!</b>\n\n"
            "Admin paneli pastki menyuga joylandi:",
            parse_mode="HTML",
            reply_markup=get_admin_keyboard(),
        )
        return

    await message.answer(
        f"👋 Salom, <b>{message.from_user.full_name}</b>!\nGold Cinema botiga xush kelibsiz.\n\n"
        f"🎁 Kuniga <b>{DAILY_FREE_LIMIT} ta</b> kinoni bepul tomosha qilishingiz mumkin. "
        "Cheksiz tomosha qilish uchun 💎 Premium xarid qilishingiz mumkin.\n\n"
        "Kino kodini yoki nomini yuboring 👇",
        parse_mode="HTML",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.message(F.text == "👑 Admin panel")
async def admin_panel_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        "🛠 <b>Admin Boshqaruv Paneli:</b>",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "👤 Foydalanuvchi paneli")
async def user_panel_msg(message: Message):
    if message.from_user is None:
        return
    await message.answer(
        "🎬 <b>Foydalanuvchi paneli</b>\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.callback_query(F.data == "user_panel")
async def user_panel_callback(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    await message.answer(
        "🎬 <b>Foydalanuvchi paneli</b>\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(
            "🛠 <b>Admin boshqaruv paneli</b>\nKerakli amalni tanlang:",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )


@dp.callback_query(F.data == "premium_info")
async def premium_info(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(
            premium_offer_text(),
            parse_mode="HTML",
            reply_markup=premium_plans_keyboard(),
        )


@dp.message(F.text == "💎 Premium")
async def premium_info_msg(message: Message):
    if message.from_user is None:
        return
    register_user(message.from_user)
    await message.answer(
        premium_offer_text(),
        parse_mode="HTML",
        reply_markup=premium_plans_keyboard(),
    )


@dp.callback_query(F.data.startswith("premium_plan:"))
async def premium_plan_selected(call: CallbackQuery, state: FSMContext):
    plans = {
        "week": "1 hafta — 15 000 so'm",
        "month": "1 oy — 35 000 so'm",
        "quarter": "3 oy — 90 000 so'm",
        "year": "1 yil — 300 000 so'm",
    }
    if not call.data:
        await call.answer("❌ Tarif topilmadi.", show_alert=True)
        return
    plan_code = call.data.split(":", 1)[1]
    plan_name = plans.get(plan_code)
    if not plan_name:
        await call.answer("❌ Tarif topilmadi.", show_alert=True)
        return
    await state.set_state(PremiumPaymentState.waiting_receipt)
    await state.update_data(plan=plan_name)
    await call.answer("✅ Tarif tanlandi!")
    message = get_callback_message(call)
    if message:
        card_number = CARD_NUMBER or "Karta raqami sozlanmagan"
        card_name = CARD_NAME or "Karta egasi ko'rsatilmagan"
        await message.answer(
            f"💎 <b>Tanlangan tarif:</b> {plan_name}\n\n"
            f"💳 <b>Karta raqami:</b> <code>{escape(card_number)}</code>\n"
            f"👤 <b>Karta egasi:</b> {escape(card_name)}\n\n"
            "To'lovni amalga oshirgach, chek rasmini yoki faylini shu chatga yuboring.\n"
            f"Chek admin @{ADMIN_USERNAME} ga yuboriladi.",
            parse_mode="HTML",
        )


@dp.message(PremiumPaymentState.waiting_receipt, F.photo)
@dp.message(PremiumPaymentState.waiting_receipt, F.document)
async def premium_receipt_received(message: Message, state: FSMContext):
    if message.from_user is None or ADMIN_ID == 0:
        return
    data = await state.get_data()
    plan_name = data.get("plan", "Noma'lum tarif")
    user = message.from_user
    username = f"@{user.username}" if user.username else "Username mavjud emas"
    admin_caption = (
        "💎 <b>Yangi Premium to'lov cheki</b>\n\n"
        f"📦 Tarif: <b>{escape(str(plan_name))}</b>\n"
        f"👤 Foydalanuvchi: <b>{escape(user.full_name)}</b>\n"
        f"🔗 Username: {escape(username)}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )
    try:
        if message.photo:
            await bot.send_photo(
                ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=admin_caption,
                parse_mode="HTML",
            )
        elif message.document:
            await bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=admin_caption,
                parse_mode="HTML",
            )
        else:
            return
    except (TelegramBadRequest, TelegramForbiddenError):
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi. Admin bilan bog'laning.")
        return
    await state.clear()
    await message.answer(
        "✅ Chekingiz adminga yuborildi. To'lov tasdiqlangach Premium yoqiladi.",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.message(PremiumPaymentState.waiting_receipt, F.text)
async def premium_receipt_text_received(message: Message):
    await message.answer("📎 Iltimos, to'lov chekini rasm yoki fayl ko'rinishida yuboring.")


@dp.message(F.contact)
async def save_user_contact(message: Message):
    if message.from_user is None or message.contact is None:
        return
    contact = message.contact
    if contact.user_id != message.from_user.id:
        await message.answer("⚠️ Iltimos, faqat o'zingizning telefon raqamingizni yuboring.")
        return
    register_user(message.from_user)
    USER_INFO[message.from_user.id]["phone"] = contact.phone_number
    save_data()
    await message.answer(
        "✅ Telefon raqamingiz bazaga saqlandi.",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.message(F.text == "👥 Foydalanuvchilar ro'yxati")
async def admin_users_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    if not ALL_USERS:
        await message.answer("ℹ️ Hozircha foydalanuvchilar bazasi bo'sh.", reply_markup=build_admin_reply_keyboard())
        return
    text = f"👥 <b>Foydalanuvchilar bazasi (jami: {len(ALL_USERS)} ta):</b>\n\n"
    for idx, user_id in enumerate(ALL_USERS, 1):
        info = USER_INFO.get(user_id, {})
        name = info.get("name", "Noma'lum")
        joined = info.get("joined", "Noma'lum")
        phone = info.get("phone", "Mavjud emas")
        text += (
            f"<b>{idx}. {escape(str(name))}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {escape(str(info.get('username', 'Mavjud emas')))}\n"
            f"├ Telefon: {escape(str(phone))}\n"
            f"└ Qo'shilgan: {escape(str(joined))}\n\n"
        )
    await message.answer(text[:4000], parse_mode="HTML", reply_markup=build_admin_reply_keyboard())


@dp.message(F.text == "📊 Bot statistikasi")
async def admin_stats_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    total_views = sum(VIEWS.values())
    total_likes = sum(len(movie["likes"]) for movie in MOVIES_DATABASE.values())
    await message.answer(
        f"📊 <b>Bot statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{len(ALL_USERS)}</b>\n"
        f"💎 Premium foydalanuvchilar: <b>{len(PREMIUM_USERS)}</b>\n"
        f"🎬 Kinolar: <b>{len(MOVIES_DATABASE)}</b> ta\n"
        f"👁 Ko'rishlar: <b>{total_views}</b>\n"
        f"👍 Like'lar: <b>{total_likes}</b>\n"
        f"🎁 Kunlik bepul limit: <b>{DAILY_FREE_LIMIT}</b> ta",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "💎 Premium users")
async def premium_users_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    if not PREMIUM_USERS:
        await message.answer(
            "💎 Hozircha Premium foydalanuvchilar yo'q.",
            reply_markup=build_admin_reply_keyboard(),
        )
        return
    lines = [f"💎 <b>Premium foydalanuvchilar ({len(PREMIUM_USERS)} ta):</b>\n"]
    users_updated = False
    for index, user_id in enumerate(PREMIUM_USERS, 1):
        info = USER_INFO.get(user_id, {})
        try:
            chat = await bot.get_chat(user_id)
            current_username = f"@{chat.username}" if chat.username else "Mavjud emas"
            if info.get("username") != current_username:
                USER_INFO.setdefault(user_id, {}).update(
                    {"name": chat.full_name, "username": current_username}
                )
                info = USER_INFO[user_id]
                users_updated = True
        except (TelegramBadRequest, TelegramForbiddenError):
            pass
        name = escape(str(info.get("name", "Noma'lum")))
        username = escape(str(info.get("username", "Mavjud emas")))
        phone = escape(str(info.get("phone", "Mavjud emas")))
        lines.append(
            f"{index}. <b>{name}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {username}\n"
            f"└ Telefon: {phone}\n"
        )
    if users_updated:
        save_data()
    await message.answer(
        "\n".join(lines)[:4000],
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "📥 Bazani yuklab olish")
async def export_database_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    save_data()
    await message.answer_document(
        document=FSInputFile(USERS_DATA_FILE),
        caption="📥 Foydalanuvchilar bazasi (users_database.json)",
        reply_markup=build_admin_reply_keyboard(),
    )
    await message.answer_document(
        document=FSInputFile(DATA_FILE),
        caption="📥 Kino va bot bazasi (gold_cinema_data.json)",
    )


@dp.message(F.text == "💾 Ma'lumotlarni saqlash")
async def save_database_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    save_data()
    await message.answer(
        "✅ Barcha ma'lumotlar saqlandi.",
        reply_markup=build_admin_reply_keyboard(),
    )


def build_movie_admin_list() -> str:
    lines = [f"📚 <b>Kino ro'yxati ({len(MOVIES_DATABASE)} ta)</b>\n"]
    for code in sorted(MOVIES_DATABASE, key=movie_code_sort_key):
        movie = MOVIES_DATABASE[code]
        badges = []
        if movie.get("is_premium"):
            badges.append("💎")
        if movie.get("is_premiere"):
            badges.append("🎬")
        lines.append(f"<code>{code}</code> — {escape(str(movie.get('name', 'Nomsiz')))} {' '.join(badges)}")
    return "\n".join(lines)[:4000]


async def start_movie_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddMovie.file_id)
    await message.answer(
        "➕ <b>Yangi kino qo'shish</b>\n\n"
        "Avval video yoki video-hujjatni shu chatga yuboring.\n"
        "Bekor qilish uchun /cancel yuboring.",
        parse_mode="HTML",
    )


@dp.message(F.text == "/cancel")
async def cancel_admin_action(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.clear()
        await message.answer("✅ Amal bekor qilindi.", reply_markup=build_admin_reply_keyboard())


@dp.callback_query(F.data == "admin_add")
async def admin_add_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await start_movie_add(message, state)


@dp.message(AddMovie.file_id, F.video)
@dp.message(AddMovie.file_id, F.document)
async def movie_add_media(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    if message.video:
        file_id, media_type = message.video.file_id, "video"
    elif message.document:
        file_id, media_type = message.document.file_id, "document"
    else:
        return
    await state.update_data(file_id=file_id, media_type=media_type)
    await state.set_state(AddMovie.name)
    await message.answer("1/8 🎬 Kino nomini yuboring:")


async def save_add_movie_field(message: Message, state: FSMContext, field: str, next_state: State, prompt: str):
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    value = message.text.strip()
    if not value:
        await message.answer("⚠️ Bu maydon bo'sh bo'lmasligi kerak.")
        return
    await state.update_data({field: value})
    await state.set_state(next_state)
    await message.answer(prompt)


@dp.message(AddMovie.name, F.text)
async def movie_add_name(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "name", AddMovie.til, "2/8 🗣 Tilini yuboring (masalan: O'zbek tilida):")


@dp.message(AddMovie.til, F.text)
async def movie_add_til(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "til", AddMovie.sifat, "3/8 📼 Sifatini yuboring (masalan: 1080p):")


@dp.message(AddMovie.sifat, F.text)
async def movie_add_sifat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "sifat", AddMovie.yil, "4/8 📅 Chiqqan yilini yuboring:")


@dp.message(AddMovie.yil, F.text)
async def movie_add_yil(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "yil", AddMovie.janr, "5/8 🎭 Janrini yuboring:")


@dp.message(AddMovie.janr, F.text)
async def movie_add_janr(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "janr", AddMovie.davlat, "6/8 🌍 Davlatini yuboring:")


@dp.message(AddMovie.davlat, F.text)
async def movie_add_davlat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "davlat", AddMovie.davomiyligi, "7/8 ⏳ Davomiyligini yuboring:")


@dp.message(AddMovie.davomiyligi, F.text)
async def movie_add_duration(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Davomiylikni matn ko'rinishida yuboring.")
        return
    await state.update_data(davomiyligi=message.text.strip())
    await state.set_state(AddMovie.is_premium)
    await message.answer("8/8 💎 Premium kino bo'ladimi? <b>ha</b> yoki <b>yo'q</b> deb yuboring:", parse_mode="HTML")


@dp.message(AddMovie.is_premium, F.text)
async def movie_add_finish(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    answer = message.text.strip().lower()
    if answer not in {"ha", "yo'q", "yoq", "yes", "no"}:
        await message.answer("⚠️ Faqat 'ha' yoki 'yo'q' deb yuboring.")
        return
    data = await state.get_data()
    required_fields = ("file_id", "name", "til", "sifat", "yil", "janr", "davlat", "davomiyligi")
    if any(not data.get(field) for field in required_fields):
        await state.clear()
        await message.answer("❌ Kino qo'shish sessiyasi to'liq emas. Qaytadan boshlang.")
        return
    code = get_next_movie_code()
    MOVIES_DATABASE[code] = {
        "file_id": str(data["file_id"]), "name": capitalize_movie_text(str(data["name"])),
        "til": capitalize_movie_text(str(data["til"])), "sifat": capitalize_movie_text(str(data["sifat"])),
        "yil": str(data["yil"]), "janr": capitalize_movie_text(str(data["janr"])),
        "davlat": capitalize_movie_text(str(data["davlat"])), "davomiyligi": str(data["davomiyligi"]),
        "is_premium": answer in {"ha", "yes"}, "is_premiere": False,
        "likes": set(), "dislikes": set(), "trailer_file_id": None,
        "media_type": data.get("media_type", "video"),
    }
    save_data()
    await state.clear()
    await message.answer(
        f"✅ Kino muvaffaqiyatli qo'shildi!\n\n🎬 {escape(MOVIES_DATABASE[code]['name'])}\n🔎 Kod: <code>{code}</code>",
        parse_mode="HTML", reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text.in_({"➕ Kino qo'shish", "🗑 Kino o'chirish", "✏️ Kino tahrirlash", "🎬 Premyera sozlash", "👑 Premium berish/olish", "📚 Kino ro'yxati"}))
async def admin_movie_action_msg(message: Message, state: FSMContext):
    if not message.from_user or message.from_user.id != ADMIN_ID:
        return
    if message.text == "➕ Kino qo'shish":
        await start_movie_add(message, state)
    elif message.text == "🗑 Kino o'chirish":
        await state.set_state(DeleteMovie.code)
        await message.answer("🗑 O'chiriladigan kino kodini yuboring (masalan: 51):\nBekor qilish uchun /cancel yuboring.")
    elif message.text == "✏️ Kino tahrirlash":
        await state.set_state(EditMovie.code)
        await message.answer("✏️ Tahrirlanadigan kino kodini yuboring:")
    elif message.text == "🎬 Premyera sozlash":
        await state.set_state(AdminPremiere.code)
        await message.answer("🎬 Premyera qilinadigan kino kodini yuboring. 0 yuborsangiz premyera o'chadi.")
    elif message.text == "👑 Premium berish/olish":
        await state.set_state(AdminPremium.user_id)
        await message.answer("👑 Foydalanuvchi Telegram ID sini yuboring:")
    elif message.text == "📚 Kino ro'yxati":
        await message.answer(build_movie_admin_list(), parse_mode="HTML", reply_markup=build_admin_reply_keyboard())


@dp.message(DeleteMovie.code)
async def delete_movie_by_code(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    code = message.text.strip()
    movie = MOVIES_DATABASE.pop(code, None)
    await state.clear()
    if movie is None:
        await message.answer("❌ Bunday kodli kino topilmadi.", reply_markup=build_admin_reply_keyboard())
        return
    for favorites in FAVORITES.values():
        favorites.discard(code)
    global CURRENT_PREMIERE
    if CURRENT_PREMIERE == code:
        CURRENT_PREMIERE = None
    save_data()
    await message.answer(
        f"✅ <b>{escape(str(movie['name']))}</b> o'chirildi.",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "📢 Xabar yuborish")
async def admin_broadcast_msg(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.set_state(BroadcastState.message)
        await message.answer("📢 Yuboriladigan xabar matnini kiriting:")


@dp.message(F.text == "🗳 So'rovnoma yuborish")
async def admin_poll_msg(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.set_state(AdminPollState.waiting)
        await message.answer("🗳 Format: Savol | Variant 1 | Variant 2 | Variant 3")


# ======================================================================================
#  FOYDALANUVCHILAR BAZASI VA STATISTIKA (ADMIN)
# ======================================================================================

@dp.callback_query(F.data == "admin_users")
async def show_users_list(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return

    if not ALL_USERS:
        message = get_callback_message(call)
        if message is None:
            await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
            return
        await message.edit_text("ℹ️ Hozircha foydalanuvchilar bazasi bo'sh.", reply_markup=build_admin_panel_keyboard())
        return

    text = f"👥 <b>Foydalanuvchilar Bazasi (Jami: {len(ALL_USERS)} ta):</b>\n\n"

    for idx, user_id in enumerate(ALL_USERS, 1):
        info = USER_INFO.get(user_id, {})
        name = escape(str(info.get("name", "Noma'lum")))
        username = escape(str(info.get("username", "Mavjud emas")))
        phone = escape(str(info.get("phone", "Mavjud emas")))
        joined = escape(str(info.get("joined", "Noma'lum")))
        is_premium = "💎 Premium" if user_id in PREMIUM_USERS else "🆓 Bepul"

        text += (
            f"<b>{idx}. {name}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {username}\n"
            f"├ Telefon: {phone}\n"
            f"├ Obuna: {is_premium}\n"
            f"└ Qo'shilgan: {joined}\n\n"
        )

    if len(text) > 4000:
        text = text[:3900] + "\n\n⚠️ <i>Ro'yxat juda uzunligi sababli bir qismi qisqartirildi.</i>"

    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]])
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)


@dp.callback_query(F.data == "admin_stats")
async def show_bot_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return

    total_views = sum(VIEWS.values())
    total_likes = sum(len(m["likes"]) for m in MOVIES_DATABASE.values())
    uptime = datetime.now() - BOT_START_TIME

    text = (
        "📊 <b>Bot statistikasi:</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{len(ALL_USERS)}</b>\n"
        f"💎 Premium foydalanuvchilar: <b>{len(PREMIUM_USERS)}</b>\n"
        f"🎬 Kinolar bazasi: <b>{len(MOVIES_DATABASE)}</b> ta\n"
        f"👁 Jami ko'rishlar: <b>{total_views}</b>\n"
        f"👍 Jami like'lar: <b>{total_likes}</b>\n"
        f"🎁 Kunlik bepul limit: <b>{DAILY_FREE_LIMIT}</b> ta\n"
        f"🎬 Joriy premyera: <b>{MOVIES_DATABASE[CURRENT_PREMIERE]['name'] if CURRENT_PREMIERE and CURRENT_PREMIERE in MOVIES_DATABASE else 'Yo\u02bbq'}</b>\n"
        f"⏱ Bot ishlash vaqti: <b>{str(uptime).split('.')[0]}</b>"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]])
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)


@dp.callback_query(F.data == "admin_premium")
async def show_premium_users_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    if not PREMIUM_USERS:
        text = "💎 <b>Premium users</b>\n\nHozircha Premium foydalanuvchilar yo'q."
    else:
        lines = [f"💎 <b>Premium users ({len(PREMIUM_USERS)} ta)</b>\n"]
        for index, user_id in enumerate(PREMIUM_USERS, 1):
            info = USER_INFO.get(user_id, {})
            name = escape(str(info.get("name", "Noma'lum")))
            username = escape(str(info.get("username", "Mavjud emas")))
            lines.append(
                f"{index}. <b>{name}</b> — <code>{user_id}</code> ({username})"
            )
        text = "\n".join(lines)
    await message.edit_text(
        text[:4000],
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin_panel")]
            ]
        ),
    )


@dp.callback_query(F.data == "admin_save")
async def save_from_admin_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    save_data()
    await call.answer("✅ Ma'lumotlar saqlandi!", show_alert=True)


@dp.callback_query(F.data == "admin_export")
async def export_from_admin_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    save_data()
    await call.answer("📥 Baza tayyorlanmoqda...")
    message = get_callback_message(call)
    if message:
        await message.answer_document(
            document=FSInputFile(USERS_DATA_FILE),
            caption="📥 Foydalanuvchilar bazasi (users_database.json)",
        )
        await message.answer_document(
            document=FSInputFile(DATA_FILE),
            caption="📥 Kino va bot bazasi (gold_cinema_data.json)",
        )


@dp.callback_query(F.data == "admin_delete")
async def admin_delete_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(DeleteMovie.code)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("🗑 O'chiriladigan kino kodini yuboring (masalan: 51):")


def build_edit_fields_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Nomi", callback_data=f"editfield:{code}:name"), InlineKeyboardButton(text="🗣 Til", callback_data=f"editfield:{code}:til")],
        [InlineKeyboardButton(text="📼 Sifat", callback_data=f"editfield:{code}:sifat"), InlineKeyboardButton(text="📅 Yil", callback_data=f"editfield:{code}:yil")],
        [InlineKeyboardButton(text="🎭 Janr", callback_data=f"editfield:{code}:janr"), InlineKeyboardButton(text="🌍 Davlat", callback_data=f"editfield:{code}:davlat")],
        [InlineKeyboardButton(text="⏳ Davomiyligi", callback_data=f"editfield:{code}:davomiyligi"), InlineKeyboardButton(text="💎 Premium almashtirish", callback_data=f"edittoggle:{code}:premium")],
        [InlineKeyboardButton(text="❌ Yopish", callback_data="admin_panel")],
    ])


@dp.callback_query(F.data == "admin_edit")
async def admin_edit_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(EditMovie.code)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("✏️ Tahrirlanadigan kino kodini yuboring:")


@dp.message(EditMovie.code, F.text)
async def admin_edit_code(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    code = message.text.strip()
    if code not in MOVIES_DATABASE:
        await message.answer("❌ Bunday kodli kino topilmadi.")
        return
    await state.update_data(code=code)
    await state.set_state(EditMovie.field)
    await message.answer(f"✏️ <b>{escape(str(MOVIES_DATABASE[code]['name']))}</b> uchun maydonni tanlang:", parse_mode="HTML", reply_markup=build_edit_fields_keyboard(code))


@dp.callback_query(F.data.startswith("editfield:"))
async def admin_edit_field(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID or not call.data:
        return
    _, code, field = call.data.split(":", 2)
    if code not in MOVIES_DATABASE:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    await state.update_data(code=code, field=field)
    await state.set_state(EditMovie.value)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(f"✏️ Yangi qiymatni yuboring ({field}):")


@dp.message(EditMovie.value, F.text)
async def admin_edit_value(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    data = await state.get_data()
    code, field = data.get("code"), data.get("field")
    if code not in MOVIES_DATABASE or field not in {"name", "til", "sifat", "yil", "janr", "davlat", "davomiyligi"}:
        await state.clear()
        await message.answer("❌ Tahrirlash sessiyasi eskirgan.")
        return
    MOVIES_DATABASE[code][field] = capitalize_movie_text(message.text.strip())
    save_data()
    await state.clear()
    await message.answer("✅ Kino ma'lumoti yangilandi.", reply_markup=build_admin_reply_keyboard())


@dp.callback_query(F.data.startswith("edittoggle:"))
async def admin_toggle_premium_movie(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID or not call.data:
        return
    _, code, _ = call.data.split(":", 2)
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    movie["is_premium"] = not movie.get("is_premium", False)
    save_data()
    await call.answer("✅ Premium holati o'zgartirildi.", show_alert=True)


@dp.callback_query(F.data == "admin_movies")
async def admin_movies_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(build_movie_admin_list(), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin_panel")]]))


@dp.callback_query(F.data == "admin_premium_manage")
async def admin_premium_manage_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AdminPremium.user_id)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("👑 Premium beriladigan yoki olinadigan foydalanuvchi ID sini yuboring:")


@dp.message(AdminPremium.user_id, F.text)
async def admin_premium_manage_finish(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    try:
        user_id = int(message.text.strip())
    except ValueError:
        await message.answer("⚠️ ID faqat raqamlardan iborat bo'ladi.")
        return
    if user_id in PREMIUM_USERS:
        PREMIUM_USERS.remove(user_id)
        result = "olib tashlandi"
    else:
        PREMIUM_USERS.append(user_id)
        result = "berildi"
    save_data()
    await state.clear()
    await message.answer(f"✅ <code>{user_id}</code> foydalanuvchiga Premium {result}.", parse_mode="HTML", reply_markup=build_admin_reply_keyboard())


@dp.callback_query(F.data == "admin_premiere")
async def admin_premiere_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AdminPremiere.code)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("🎬 Premyera qilinadigan kino kodini yuboring. 0 yuborsangiz premyera o'chadi:")


@dp.message(AdminPremiere.code, F.text)
async def admin_premiere_finish(message: Message, state: FSMContext):
    global CURRENT_PREMIERE
    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    code = message.text.strip()
    if code == "0":
        CURRENT_PREMIERE = None
        for movie in MOVIES_DATABASE.values():
            movie["is_premiere"] = False
        save_data()
        await state.clear()
        await message.answer("✅ Premyera o'chirildi.", reply_markup=build_admin_reply_keyboard())
        return
    if code not in MOVIES_DATABASE:
        await message.answer("❌ Bunday kodli kino topilmadi.")
        return
    for movie in MOVIES_DATABASE.values():
        movie["is_premiere"] = False
    MOVIES_DATABASE[code]["is_premiere"] = True
    CURRENT_PREMIERE = code
    save_data()
    await state.clear()
    await message.answer(f"✅ <b>{escape(str(MOVIES_DATABASE[code]['name']))}</b> premyera qilindi.", parse_mode="HTML", reply_markup=build_admin_reply_keyboard())


@dp.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(BroadcastState.message)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:")


@dp.message(BroadcastState.message)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    await state.clear()
    ok, fail = await broadcast_text(message.text)
    await message.answer(f"✅ Xabar yuborildi!\nMuvaffaqiyatli: {ok} ta\nXato: {fail} ta")


@dp.callback_query(F.data == "admin_poll")
async def admin_poll_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AdminPollState.waiting)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(
            "🗳 So'rovnoma matnini quyidagi formatda yuboring:\n\n"
            "<code>Savol | Variant 1 | Variant 2 | Variant 3</code>\n\n"
            "Masalan: <code>Keyingi qaysi janrdagi kino qo'shilsin? | Qo'rqinchli | Jangari | Drama</code>",
            parse_mode="HTML",
        )


@dp.message(AdminPollState.waiting)
async def admin_poll_send(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    await state.clear()
    parts = [p.strip() for p in message.text.split("|") if p.strip()]
    if len(parts) < 3:
        await message.answer("⚠️ Kamida savol + 2 ta variant kerak. Qaytadan urinib ko'ring.")
        return
    question = parts[0]
    options: list[InputPollOption | str] = [
        InputPollOption(text=option) for option in parts[1:10]
    ]
    ok, fail = 0, 0
    for user_id in list(ALL_USERS):
        try:
            await bot.send_poll(user_id, question=question, options=options, is_anonymous=True)
            ok += 1
        except TelegramBadRequest:
            fail += 1
        await asyncio.sleep(0.05)
    await message.answer(f"✅ So'rovnoma yuborildi!\nMuvaffaqiyatli: {ok} ta\nXato: {fail} ta")


@dp.callback_query(F.data == "admin_panel_back")
async def admin_panel_back(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await call.answer()
    await message.edit_text(
        "🛠 <b>Admin boshqaruv paneli</b>\nKerakli amalni tanlang:",
        parse_mode="HTML",
        reply_markup=build_admin_panel_keyboard(),
    )


# ======================================================================================
#  ADMIN UCHUN: FAYLLARDAN FILE_ID OLISH + PREMYERA KINO YUKLASH
# ======================================================================================

def parse_premiere_caption(caption: str) -> dict:
    """
    Caption formati:
    premyera
    Nomi: ...
    Til: ...
    Sifat: ...
    Yil: ...
    Janr: ...
    Davlat: ...
    Davomiyligi: ...
    (Nomi dan boshqa qatorlar ixtiyoriy — yozilmasa standart qiymat qo'yiladi)
    """
    fields = {
        "name": "Yangi premyera kino",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": str(date.today().year),
        "janr": "Premyera",
        "davlat": "Noma'lum",
        "davomiyligi": "Noma'lum",
    }
    key_map = {
        "nomi": "name",
        "til": "til",
        "sifat": "sifat",
        "yil": "yil",
        "janr": "janr",
        "davlat": "davlat",
        "davomiyligi": "davomiyligi",
    }
    for line in caption.splitlines()[1:]:
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        if key in key_map and value.strip():
            fields[key_map[key]] = value.strip()
    return fields


def get_next_movie_code() -> str:
    """20 dan boshlab bazadagi birinchi bo'sh kino kodini qaytaradi."""
    code = 20
    while str(code) in MOVIES_DATABASE:
        code += 1
    return str(code)


def parse_movie_caption(caption: str, fallback_name: str, code: str) -> dict:
    """Oddiy kino captionidan nom va ixtiyoriy metadata ma'lumotlarini oladi."""
    fields = parse_premiere_caption(caption) if caption.strip() else {
        "name": fallback_name,
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": str(date.today().year),
        "janr": "Noma'lum",
        "davlat": "Noma'lum",
        "davomiyligi": "Noma'lum",
    }
    if fields["name"] == "Yangi premyera kino":
        for line in caption.splitlines():
            clean_line = line.strip().strip('"“”')
            if (
                clean_line
                and ":" not in clean_line
                and not clean_line.lower().startswith("premyera")
            ):
                fields["name"] = clean_line
                break
    if fields["name"] == "Yangi premyera kino":
        fields["name"] = fallback_name or f"Kino {code}"
    return fields


async def add_movie_from_media(
    message: Message,
    file_id: str,
    fallback_name: str,
    media_type: str | None = None,
) -> str:
    """Admin yuborgan video yoki hujjatni keyingi kod bilan bazaga qo'shadi."""
    code = get_next_movie_code()
    fields = parse_movie_caption(message.caption or "", fallback_name, code)
    fields = {key: capitalize_movie_text(value) for key, value in fields.items()}
    MOVIES_DATABASE[code] = {
        "file_id": file_id,
        "name": fields["name"],
        "til": fields["til"],
        "sifat": fields["sifat"],
        "yil": fields["yil"],
        "janr": fields["janr"],
        "davlat": fields["davlat"],
        "davomiyligi": fields["davomiyligi"],
        "is_premium": False,
        "is_premiere": False,
        "likes": set(),
        "dislikes": set(),
        "trailer_file_id": None,
    }
    if media_type:
        MOVIES_DATABASE[code]["media_type"] = media_type
    save_data()
    return code


@dp.message(F.video)
async def get_video_file_id(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.video is None:
        return
    file_id = message.video.file_id
    await message.reply(
        f"🔑 <b>File ID:</b> <code>{file_id}</code>\n\n"
        "Kino qo'shish uchun avval admin paneldan <b>➕ Kino qo'shish</b> ni bosing; "
        "shunda video avtomatik ravishda wizardga qabul qilinadi.",
        parse_mode="HTML",
    )


@dp.message(F.document)
async def get_document_file_id(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.document is None:
        return
    file_id = message.document.file_id
    await message.reply(
        f"🔑 <b>File ID:</b> <code>{file_id}</code>\n\n"
        "Kino qo'shish uchun avval admin paneldan <b>➕ Kino qo'shish</b> ni bosing; "
        "shunda hujjat avtomatik ravishda wizardga qabul qilinadi.",
        parse_mode="HTML",
    )


# ======================================================================================
#  KINO YUBORISH (umumiy funksiya) — FREEMIUM LIMIT SHU YERDA TEKSHIRILADI
# ======================================================================================

async def send_movie(target: Message, code: str, movie: dict, user_id: int | None = None):
    # Kino "premium" deb belgilangan bo'lsa — faqat Premium foydalanuvchilar ko'radi
    if movie.get("is_premium") and not has_premium_access(user_id):
        await target.answer(
            "💎 <b>Premium kino</b>\n\nBu kinoni ko'rish uchun Premium maqom kerak.",
            parse_mode="HTML",
            reply_markup=premium_plans_keyboard(),
        )
        return

    # Kunlik bepul limit — Premium bo'lmagan har bir foydalanuvchi uchun
    if user_id is not None and not has_premium_access(user_id):
        remaining = get_remaining_free_views(user_id)
        if remaining <= 0:
            await target.answer(
                f"🔒 Bugungi bepul limitingiz ({DAILY_FREE_LIMIT} ta kino) tugadi.\n\n"
                "💎 Premium xarid qilib, kinolarni cheksiz tomosha qiling!",
                parse_mode="HTML",
                reply_markup=premium_plans_keyboard(),
            )
            return

    send_method = target.answer_document if movie.get("media_type") == "document" else target.answer_video
    try:
        await send_method(
            **({"document": movie["file_id"]} if movie.get("media_type") == "document" else {"video": movie["file_id"]}),
            caption=build_caption(code, movie),
            parse_mode="HTML",
            reply_markup=build_movie_keyboard(code, movie, user_id),
        )
        if user_id is not None:
            VIEWS[user_id] = VIEWS.get(user_id, 0) + 1
            register_daily_view(user_id)
            save_data()
    except TelegramBadRequest:
        await target.answer("⚠️ Kinoni yuborishda xatolik yuz berdi. Telegram fayl ID eskirgan bo'lishi mumkin.")


# ======================================================================================
#  BOSH MENYU TUGMALARI: TASODIFIY, KUNNING KINOSI, TOP, TAVSIYA, SEVIMLILAR, STATISTIKA
# ======================================================================================

@dp.message(F.text == "🔴 Ko'proq kinolar")
@dp.message(F.text == "🎲 Tasodifiy kino")
@dp.callback_query(F.data == "menu_rand")
async def send_random_movie(event):
    register_user(event.from_user)
    if not MOVIES_DATABASE:
        text = "❌ Hozircha bazada kinolar mavjud emas."
        await (event.answer(text, show_alert=True) if isinstance(event, CallbackQuery) else event.answer(text))
        return

    code = random.choice(list(MOVIES_DATABASE.keys()))
    movie = MOVIES_DATABASE[code]

    if isinstance(event, CallbackQuery):
        await event.answer()
        message = get_callback_message(event)
        if message is None:
            return
        await send_movie(message, code, movie, event.from_user.id)
    else:
        await send_movie(event, code, movie, event.from_user.id)


@dp.message(F.text == "📅 Kunning kinosi")
async def daily_movie_msg(message: Message):
    if not MOVIES_DATABASE:
        await message.answer("❌ Hozircha bazada kinolar mavjud emas.")
        return
    register_user(message.from_user)
    codes = sorted(MOVIES_DATABASE.keys(), key=movie_code_sort_key)
    code = codes[date.today().toordinal() % len(codes)]
    await send_movie(message, code, MOVIES_DATABASE[code], message.from_user.id if message.from_user else None)


@dp.message(F.text == "🎬 PREMYERA KINO")
async def premiere_movie_msg(message: Message):
    if not CURRENT_PREMIERE or CURRENT_PREMIERE not in MOVIES_DATABASE:
        await message.answer("❌ Hozircha faol premyera yo'q.")
        return
    register_user(message.from_user)
    await send_movie(
        message,
        CURRENT_PREMIERE,
        MOVIES_DATABASE[CURRENT_PREMIERE],
        message.from_user.id if message.from_user else None,
    )


@dp.message(F.text == "🔥 TOP kinolar")
async def top_movies_msg(message: Message):
    ranked = sorted(
        MOVIES_DATABASE.items(),
        key=lambda item: len(item[1]["likes"]) - len(item[1]["dislikes"]),
        reverse=True,
    )[:10]
    text = "🔥 <b>TOP kinolar:</b>\n\n"
    for idx, (code, movie) in enumerate(ranked, 1):
        text += f"{idx}. <b>{movie['name']}</b> — 👍 {len(movie['likes'])} | kodi: <code>{code}</code>\n"
    await message.answer(text, parse_mode="HTML")


@dp.message(F.text == "🎯 Menga mos kino")
async def recommend_movie_msg(message: Message):
    if MOVIES_DATABASE:
        code = random.choice(list(MOVIES_DATABASE))
        await message.answer("🎯 Sizga mos kino:")
        await send_movie(message, code, MOVIES_DATABASE[code], message.from_user.id if message.from_user else None)


@dp.message(F.text == "⭐ Sevimlilarim")
async def favorites_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    codes = FAVORITES.get(user_id, set())
    matches = {code: MOVIES_DATABASE[code] for code in codes if code in MOVIES_DATABASE}
    if matches:
        await message.answer(build_results_text("⭐ <b>Sevimli kinolaringiz:</b>", matches), parse_mode="HTML")
    else:
        await message.answer("⭐ Sevimlilar ro'yxatingiz hali bo'sh.")


@dp.message(F.text == "📊 Statistikam")
async def my_stats_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    liked_count = sum(user_id in movie["likes"] for movie in MOVIES_DATABASE.values())
    remaining = get_remaining_free_views(user_id)
    remaining_text = "♾ Cheksiz (Premium)" if remaining < 0 else f"{remaining} / {DAILY_FREE_LIMIT} ta"
    await message.answer(
        f"📊 <b>Sizning statistikangiz:</b>\n\n"
        f"👁 Ko'rilgan kinolar: <b>{VIEWS.get(user_id, 0)}</b>\n"
        f"👍 Like bosilgan kinolar: <b>{liked_count}</b>\n"
        f"⭐ Sevimlilar: <b>{len(FAVORITES.get(user_id, set()))}</b>\n"
        f"🎁 Bugungi bepul limit: <b>{remaining_text}</b>",
        parse_mode="HTML",
    )


@dp.message(F.text == "📝 Kino so'rash")
async def request_movie_msg(message: Message, state: FSMContext):
    await state.set_state(MovieRequestState.waiting)
    await message.answer("📝 Qaysi kinoni topishni istaysiz? Nomini yozib yuboring.")


@dp.message(F.text == "🤝 Do'stni taklif qilish")
async def referral_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}" if BOT_USERNAME else "Bot username aniqlanmagan"
    await message.answer(f"🤝 Shaxsiy taklif havolangiz:\n<code>{link}</code>", parse_mode="HTML")


@dp.message(F.text == "🔎 Qidirish yordami")
async def search_help_msg(message: Message):
    await message.answer("🔎 Kino kodi yoki nomini chatga yozib yuboring.")


@dp.message(F.text == "📞 Admin bilan bog'lanish")
async def contact_admin_msg(message: Message):
    if ADMIN_USERNAME:
        await message.answer(f"📞 Admin bilan bog'lanish: https://t.me/{ADMIN_USERNAME}")
    else:
        await message.answer("⚠️ Admin username'i hali sozlanmagan.")


@dp.callback_query(F.data == "menu_premiere")
async def send_premiere_movie(call: CallbackQuery):
    register_user(call.from_user)
    if not CURRENT_PREMIERE or CURRENT_PREMIERE not in MOVIES_DATABASE:
        await call.answer("❌ Hozircha faol premyera yo'q.", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    await send_movie(message, CURRENT_PREMIERE, MOVIES_DATABASE[CURRENT_PREMIERE], call.from_user.id)


@dp.callback_query(F.data == "menu_daily")
async def send_daily_movie(call: CallbackQuery):
    register_user(call.from_user)
    if not MOVIES_DATABASE:
        await call.answer("❌ Hozircha bazada kinolar mavjud emas.", show_alert=True)
        return
    codes = sorted(MOVIES_DATABASE.keys(), key=movie_code_sort_key)
    index = date.today().toordinal() % len(codes)
    code = codes[index]
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    await send_movie(message, code, MOVIES_DATABASE[code], call.from_user.id)


@dp.callback_query(F.data == "menu_top")
async def show_top_movies(call: CallbackQuery):
    register_user(call.from_user)
    ranked = sorted(
        MOVIES_DATABASE.items(),
        key=lambda item: len(item[1]["likes"]) - len(item[1]["dislikes"]),
        reverse=True,
    )[:10]
    if not ranked or all(len(m["likes"]) == 0 for _, m in ranked):
        message = get_callback_message(call)
        if message:
            await message.answer("ℹ️ Hozircha hech kim like bosmagan. Birinchi bo'ling! 👍")
        await call.answer()
        return

    text = "🔥 <b>TOP kinolar:</b>\n\n"
    for idx, (code, movie) in enumerate(ranked, 1):
        text += f"{idx}. <b>{movie['name']}</b> — 👍 {len(movie['likes'])} | kodi: <code>{code}</code>\n"
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "menu_recommend")
async def recommend_movie(call: CallbackQuery):
    user_id = call.from_user.id
    register_user(call.from_user)

    liked_codes = {code for code, m in MOVIES_DATABASE.items() if user_id in m["likes"]} | FAVORITES.get(user_id, set())
    if not liked_codes:
        await call.answer("ℹ️ Hali hech qanday kinoga like/sevimli belgisi qo'ymadingiz — tasodifiy kino tavsiya qilamiz.", show_alert=True)
        code = random.choice(list(MOVIES_DATABASE.keys()))
    else:
        genre_words = set()
        for c in liked_codes:
            genre_words.update(re.split(r"[,\s]+", MOVIES_DATABASE[c].get("janr", "").lower()))
        candidates = [
            c for c, m in MOVIES_DATABASE.items()
            if c not in liked_codes and genre_words & set(re.split(r"[,\s]+", m.get("janr", "").lower()))
        ]
        code = random.choice(candidates) if candidates else random.choice(list(MOVIES_DATABASE.keys()))

    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    await message.answer("🎯 Sizga mos kino:")
    await send_movie(message, code, MOVIES_DATABASE[code], user_id)


@dp.callback_query(F.data == "menu_favorites")
async def show_favorites(call: CallbackQuery):
    user_id = call.from_user.id
    register_user(call.from_user)
    codes = FAVORITES.get(user_id, set())
    message = get_callback_message(call)
    await call.answer()
    if not codes:
        if message:
            await message.answer("⭐ Sevimlilar ro'yxatingiz hali bo'sh. Kino ostidagi ⭐ tugmasini bosing!")
        return
    matches = {c: MOVIES_DATABASE[c] for c in codes if c in MOVIES_DATABASE}
    if message:
        await message.answer(build_results_text("⭐ <b>Sevimli kinolaringiz:</b>", matches), parse_mode="HTML")


@dp.callback_query(F.data == "menu_stats")
async def show_my_stats(call: CallbackQuery):
    user_id = call.from_user.id
    register_user(call.from_user)
    info = USER_INFO.get(user_id, {})
    liked_count = sum(1 for m in MOVIES_DATABASE.values() if user_id in m["likes"])
    ref_count = len(REFERRALS.get(user_id, set()))
    is_premium = "💎 Ha" if user_id in PREMIUM_USERS else "🆓 Yo'q"
    remaining = get_remaining_free_views(user_id)
    remaining_text = "♾ Cheksiz (Premium)" if remaining < 0 else f"{remaining} / {DAILY_FREE_LIMIT} ta"

    text = (
        "📊 <b>Sizning statistikangiz:</b>\n\n"
        f"👁 Ko'rilgan kinolar: <b>{VIEWS.get(user_id, 0)}</b>\n"
        f"👍 Like bosilgan kinolar: <b>{liked_count}</b>\n"
        f"⭐ Sevimlilar: <b>{len(FAVORITES.get(user_id, set()))}</b>\n"
        f"🤝 Taklif qilingan do'stlar: <b>{ref_count}</b>\n"
        f"💎 Premium: <b>{is_premium}</b>\n"
        f"🎁 Bugungi bepul limit: <b>{remaining_text}</b>\n"
        f"📅 Ro'yxatdan o'tgan: <b>{info.get('joined', 'Noma\u02bblum')}</b>"
    )
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "menu_referral")
async def show_referral_link(call: CallbackQuery):
    user_id = call.from_user.id
    register_user(call.from_user)
    count = len(REFERRALS.get(user_id, set()))
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}" if BOT_USERNAME else "(bot username aniqlanmoqda, birozdan keyin urinib ko'ring)"
    text = (
        "🤝 <b>Do'stlaringizni taklif qiling!</b>\n\n"
        f"Sizning shaxsiy havolangiz:\n<code>{link}</code>\n\n"
        f"Hozircha taklif qilinganlar: <b>{count}</b> ta\n"
        "3 ta do'stingiz botga qo'shilsa — 💎 Premium maqomga ega bo'lasiz!"
    )
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(text, parse_mode="HTML")


@dp.callback_query(F.data == "menu_request")
async def request_movie_start(call: CallbackQuery, state: FSMContext):
    register_user(call.from_user)
    await state.set_state(MovieRequestState.waiting)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("📝 Qaysi kinoni topishni istaysiz? Nomini yozib yuboring — adminga uzatamiz.")


@dp.message(MovieRequestState.waiting)
async def request_movie_finish(message: Message, state: FSMContext):
    if message.from_user is None or message.text is None:
        return
    await state.clear()
    user = message.from_user
    await message.answer("✅ So'rovingiz qabul qilindi! Tez orada ko'rib chiqamiz.")
    if ADMIN_ID:
        try:
            requester_name = escape(user.full_name or "Noma'lum")
            requested_movie = escape(message.text)
            await bot.send_message(
                ADMIN_ID,
                f"📝 <b>Yangi kino so'rovi</b>\n\n"
                f"👤 Kimdan: {requester_name} "
                f"(@{escape(user.username or '—')}, ID: <code>{user.id}</code>)\n"
                f"🎬 So'ralgan kino: {requested_movie}",
                parse_mode="HTML",
            )
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data == "menu_search_help")
async def search_help(call: CallbackQuery):
    await call.answer(
        "🔎 Kino kodini (masalan: 1, 2, 3...) yoki kino nomini (masalan: 'ekzorzist') "
        "to'g'ridan-to'g'ri chatga yozib yuboring!",
        show_alert=True,
    )


@dp.callback_query(F.data == "menu_home")
async def home_callback(call: CallbackQuery):
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await call.answer()
    await message.edit_text(
        f"👋 Salom, <b>{call.from_user.full_name}</b>!\nGold Cinema botiga xush kelibsiz.",
        parse_mode="HTML",
        reply_markup=build_main_menu_keyboard(),
    )


# ======================================================================================
#  LIKE / DISLIKE / SEVIMLILAR (⭐) TUGMALARI
# ======================================================================================

@dp.callback_query(F.data.startswith("like:"))
async def like_movie(call: CallbackQuery):
    if not call.data:
        await call.answer("❌ Noto'g'ri tugma.", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    user_id = call.from_user.id
    if user_id in movie["likes"]:
        movie["likes"].discard(user_id)
        await call.answer("👍 Like olib tashlandi.")
    else:
        movie["likes"].add(user_id)
        movie["dislikes"].discard(user_id)
        await call.answer("👍 Like qo'yildi!")
    save_data()
    message = get_callback_message(call)
    if message:
        try:
            await message.edit_reply_markup(reply_markup=build_movie_keyboard(code, movie, user_id))
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("dislike:"))
async def dislike_movie(call: CallbackQuery):
    if not call.data:
        await call.answer("❌ Noto'g'ri tugma.", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    user_id = call.from_user.id
    if user_id in movie["dislikes"]:
        movie["dislikes"].discard(user_id)
        await call.answer("👎 Dislike olib tashlandi.")
    else:
        movie["dislikes"].add(user_id)
        movie["likes"].discard(user_id)
        await call.answer("👎 Dislike qo'yildi.")
    save_data()
    message = get_callback_message(call)
    if message:
        try:
            await message.edit_reply_markup(reply_markup=build_movie_keyboard(code, movie, user_id))
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("fav:"))
async def toggle_favorite(call: CallbackQuery):
    if not call.data:
        await call.answer("❌ Noto'g'ri tugma.", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    user_id = call.from_user.id
    favs = FAVORITES.setdefault(user_id, set())
    if code in favs:
        favs.discard(code)
        await call.answer("❌ Sevimlilardan olib tashlandi.")
    else:
        favs.add(code)
        await call.answer("⭐ Sevimlilarga qo'shildi!")
    save_data()
    message = get_callback_message(call)
    if message:
        try:
            await message.edit_reply_markup(reply_markup=build_movie_keyboard(code, movie, user_id))
        except TelegramBadRequest:
            pass


# ======================================================================================
#  KINO KODI VA NOM BO'YICHA QIDIRUV (matnli xabarlar)
# ======================================================================================

@dp.message(StateFilter(None), F.text.isdigit())
async def get_movie_by_code(message: Message):
    if message.text is None:
        return
    register_user(message.from_user)
    code = message.text.strip()
    user_id = message.from_user.id if message.from_user else None
    if code in MOVIES_DATABASE:
        await send_movie(message, code, MOVIES_DATABASE[code], user_id)
    else:
        await message.answer("❌ Bunday kodli kino topilmadi. Qayta urinib ko'ring.")


@dp.message(StateFilter(None), F.text)
async def search_movie_by_name(message: Message):
    if message.text is None:
        return
    register_user(message.from_user)
    matches = find_movie_matches(message.text)
    if not matches:
        await message.answer(
            "❌ Bunday nomdagi kino topilmadi.\n"
            "🔎 Kino kodini yoki to'g'ri nomini kiriting, yoki /start orqali menyuga qayting."
        )
        return
    if len(matches) == 1:
        code, movie = next(iter(matches.items()))
        user_id = message.from_user.id if message.from_user else None
        await send_movie(message, code, movie, user_id)
    else:
        await message.answer(build_results_text("🔎 <b>Topilgan kinolar:</b>", matches), parse_mode="HTML")


# ======================================================================================
#  INLINE REJIM (@bot_username kino nomi)
# ======================================================================================

@dp.inline_query()
async def inline_search(inline_query: InlineQuery):
    query = inline_query.query.strip()
    matches = find_movie_matches(query) if query else dict(list(MOVIES_DATABASE.items())[:10])

    results = []
    for code, movie in list(matches.items())[:20]:
        if movie.get("media_type") == "document":
            results.append(
                InlineQueryResultArticle(
                    id=code,
                    title=movie["name"],
                    description=f"{movie['yil']} | {movie['janr']}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"🎬 {movie['name']} — kodi: {code}\nBotga o'tib shu kodni yuboring: @{BOT_USERNAME}"
                    ),
                )
            )
        else:
            results.append(
                InlineQueryResultCachedVideo(
                    id=code,
                    video_file_id=movie["file_id"],
                    title=movie["name"],
                    description=f"{movie['yil']} | {movie['janr']}",
                    caption=build_caption(code, movie),
                    parse_mode="HTML",
                )
            )
    await inline_query.answer(results, cache_time=30, is_personal=True)


# ======================================================================================
#  ISHLATISH
# ======================================================================================

async def main():
    global BOT_USERNAME
    me = await bot.get_me()
    BOT_USERNAME = me.username or ""
    print("Bot muvaffaqiyatli ishga tushdi...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot to'xtatildi.")