import asyncio
import aiohttp
import json
import os
import random
import re
from datetime import date, datetime, timedelta
from html import escape
from uuid import uuid4

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
CARD_NUMBER = os.getenv("CARD_NUMBER", "").strip()
CARD_NAME = os.getenv("CARD_NAME", "").strip()
PREMIUM_PLANS = {
    "day": {"period": "1 kun", "price": 2000, "duration": timedelta(days=1)},
    "week": {"period": "1 hafta", "price": 7000, "duration": timedelta(days=7)},
    "month": {"period": "1 oy", "price": 20000, "duration": timedelta(days=30)},
    "year": {"period": "1 yil", "price": 150000, "duration": timedelta(days=365)},
}

# Kunlik bepul limit 0 bo'lsa, kinolar cheksiz ko'riladi.
DAILY_FREE_LIMIT = 0

PREMIUM_USERS = [
    int(user_id)
    for user_id in re.findall(
        r"[0-9]+",
        os.getenv("PREMIUM_USERS", os.getenv("PREMIUM_USERs", "")),
    )
]
PREMIUM_USERS_CONFIGURED = "PREMIUM_USERS" in os.environ or "PREMIUM_USERs" in os.environ
INSTAGRAM_ACCOUNTS = ("boxerlife26", "gold_cinema_pro")
ALL_USERS = set()          # Botdan foydalangan barcha foydalanuvchilar ID lari
USER_INFO = {}              # {user_id: {"name": str, "username": str, "joined": str}}
INSTAGRAM_CONFIRMED_USERS: set[int] = set()

FAVORITES: dict[int, set[str]] = {}     # {user_id: {code, code, ...}}
VIEWS: dict[int, int] = {}              # {user_id: nechta kino ko'rgani (umumiy)}
DAILY_VIEWS: dict[int, dict] = {}       # {user_id: {"date": "YYYY-MM-DD", "count": int}}
REFERRALS: dict[int, set[int]] = {}     # {referrer_id: {taklif qilinganlar}}
REFERRED_BY: dict[int, int] = {}        # {user_id: kim taklif qilgani}
PREMIUM_SUBSCRIPTIONS: dict[int, str] = {}  # {user_id: amal qilish muddati (ISO datetime)}
PREMIUM_OVERRIDES: dict[int, bool] = {}  # Admin bergan yoki bekor qilgan Premium holati
PENDING_PREMIUM_PAYMENTS: dict[str, dict] = {}
LIBRARY_PRICE = "9 900 so'm/oy"
BOT_SETTINGS = {
    "card_number": CARD_NUMBER,
    "card_name": CARD_NAME,
    "instagram_required": True,
    "instagram_accounts": list(INSTAGRAM_ACCOUNTS),
    "daily_free_limit": DAILY_FREE_LIMIT,
    "premium_prices": {code: int(plan["price"]) for code, plan in PREMIUM_PLANS.items()},
    "library_price": 9900,
}
LIBRARY_SUBSCRIPTIONS: dict[int, str] = {}
PENDING_LIBRARY_PAYMENTS: dict[str, dict] = {}
WATCH_LATER: dict[int, set[str]] = {}
LIBRARY_HISTORY: dict[int, list[dict[str, str]]] = {}

CURRENT_PREMIERE: str | None = None     # Hozirgi premyera kino kodi
DATA_FILE = os.path.join(BASE_DIR, "gold_cinema_data.json")
USERS_DATA_FILE = os.path.join(BASE_DIR, "users_database.json")

BOT_START_TIME = datetime.now()
BOT_USERNAME = ""  # main() ichida to'ldiriladi

session = AiohttpSession(timeout=60)
bot = Bot(token=BOT_TOKEN, session=session)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


def format_som(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")


def premium_plan_label(plan_code: str) -> str:
    plan = PREMIUM_PLANS[plan_code]
    return f"{plan['period']} — {format_som(int(plan['price']))} so'm"


def apply_bot_settings(settings: object) -> None:
    global CARD_NUMBER, CARD_NAME, DAILY_FREE_LIMIT, INSTAGRAM_ACCOUNTS, LIBRARY_PRICE
    if not isinstance(settings, dict):
        return
    card_number = settings.get("card_number")
    if isinstance(card_number, str):
        CARD_NUMBER = card_number
        BOT_SETTINGS["card_number"] = card_number
    card_name = settings.get("card_name")
    if isinstance(card_name, str):
        CARD_NAME = card_name
        BOT_SETTINGS["card_name"] = card_name
    required = settings.get("instagram_required")
    if isinstance(required, bool):
        BOT_SETTINGS["instagram_required"] = required
    accounts = settings.get("instagram_accounts")
    if isinstance(accounts, list) and all(isinstance(item, str) for item in accounts):
        normalized_accounts = [item.lstrip("@").strip() for item in accounts if item.strip()]
        if normalized_accounts:
            INSTAGRAM_ACCOUNTS = tuple(normalized_accounts)
            BOT_SETTINGS["instagram_accounts"] = normalized_accounts
    limit = settings.get("daily_free_limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and limit >= 0:
        DAILY_FREE_LIMIT = limit
        BOT_SETTINGS["daily_free_limit"] = limit
    prices = settings.get("premium_prices")
    if isinstance(prices, dict):
        for code, amount in prices.items():
            if code in PREMIUM_PLANS and isinstance(amount, int) and not isinstance(amount, bool) and amount >= 0:
                PREMIUM_PLANS[code]["price"] = amount
                BOT_SETTINGS["premium_prices"][code] = amount
    library_price = settings.get("library_price")
    if isinstance(library_price, int) and not isinstance(library_price, bool) and library_price >= 0:
        BOT_SETTINGS["library_price"] = library_price
        LIBRARY_PRICE = f"{format_som(library_price)} so'm/oy"


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 Karta ma'lumotlari", callback_data="admin_setting:card")],
        [
            InlineKeyboardButton(text="📷 Obuna sahifalari", callback_data="admin_setting:accounts"),
            InlineKeyboardButton(
                text="🔒 Obuna talabini " + ("o'chirish" if BOT_SETTINGS["instagram_required"] else "yoqish"),
                callback_data="admin_setting:toggle_subscription",
            ),
        ],
        [InlineKeyboardButton(text="🎬 Bepul kino limiti", callback_data="admin_setting:limit")],
    ]
    rows.extend(
        [InlineKeyboardButton(
            text=f"💎 Premium: {premium_plan_label(code)}",
            callback_data=f"admin_setting:premium:{code}",
        )]
        for code in PREMIUM_PLANS
    )
    rows.extend([
        [InlineKeyboardButton(text=f"📚 Kutubxona narxi: {LIBRARY_PRICE}", callback_data="admin_setting:library_price")],
        [InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin_panel")],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_settings_text() -> str:
    accounts = ", ".join(f"@{name}" for name in INSTAGRAM_ACCOUNTS) or "Kiritilmagan"
    subscription_status = "Yoqilgan" if BOT_SETTINGS["instagram_required"] else "O'chirilgan"
    limit = f"{DAILY_FREE_LIMIT} ta/kun" if DAILY_FREE_LIMIT else "Cheksiz"
    return (
        "⚙️ <b>Bot sozlamalari</b>\n\n"
        f"💳 Karta: <code>{escape(CARD_NUMBER or 'kiritilmagan')}</code>\n"
        f"👤 Karta egasi: {escape(CARD_NAME or 'kiritilmagan')}\n"
        f"📷 Obuna talabi: <b>{subscription_status}</b>\n"
        f"📣 Obuna sahifalari: {escape(accounts)}\n"
        f"🎬 Bepul kino limiti: <b>{limit}</b>\n"
        f"📚 Kutubxona: <b>{escape(LIBRARY_PRICE)}</b>\n"
        "Quyidagi tugmalardan sozlamani tanlang:"
    )


def premium_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"📆 {premium_plan_label(code)}",
                    callback_data=f"premium_plan:{code}",
                )
            ]
            for code in PREMIUM_PLANS
        ]
    )


def gift_premium_plans_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📆 {premium_plan_label(code)}", callback_data=f"gift_plan:{code}")]
        for code in PREMIUM_PLANS
    ])


class AddMovie(StatesGroup):
    name = State()
    til = State()
    sifat = State()
    yil = State()
    janr = State()
    davlat = State()
    davomiyligi = State()
    file_id = State()


class DeleteMovie(StatesGroup):
    code = State()


class EditMovie(StatesGroup):
    code = State()
    field = State()
    value = State()


class AdminPremium(StatesGroup):
    user_id = State()


class AdminVip(StatesGroup):
    user_id = State()


class AdminSettings(StatesGroup):
    value = State()


class AdminPremiere(StatesGroup):
    code = State()


class BroadcastState(StatesGroup):
    message = State()


class MovieRequestState(StatesGroup):
    waiting = State()


class MovieSearchState(StatesGroup):
    waiting = State()


class AdminPollState(StatesGroup):
    waiting = State()


class PremiumPaymentState(StatesGroup):
    waiting_receipt = State()


class LibraryPaymentState(StatesGroup):
    waiting_receipt = State()


class GiftPremiumState(StatesGroup):
    recipient_id = State()


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
        "janr": "Romantika, komediya",
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
        "file_id": "BAACAgUAAxkBAAIJCGq7QmXtRHyhopaJ2QHZMwFjCiGxAAL2DAACvm4JVPV6TChLzLFCPQQ",
      "name": "Qaytarib Bo'lmas",
      "til": "O'zbek Tilida",
      "sifat": "1080P",
      "yil": "2026",
      "janr": "Jangari, kriminal ",
      "davlat": "Fransiya",
      "davomiyligi": "1 Soat 37 Minut",
        "is_premium": False,
    },
    "16": {
       "file_id": "BAACAgQAAxkBAAIJCmq7RAR1bN7FUgG4sH3_8Y_mvTTEAAIpGAAC4zCZUtS4mXHsficNPQQ",
        "name": "Olov",
        "til": "O'zbek tilida",
        "sifat": "1080P",
        "yil": "2024",
        "janr": "Ujas, triller",
        "davlat": "Qirg'iston",
        "davomiyligi": "1 soat 43 minut",
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
    },
    "20": {
        "file_id": "BAACAgQAAxkBAAIHVGqvsnZTBzvr7ePv9aPZqJjLOwRiAAJGIQAC-gyAUWvwB148Man5PQQ",
        "name": "Li Kronning Mumiyosi",
        "til": "O'zbek tilida",
        "sifat": "1080p",
        "yil": "2025",
        "janr": "Qo'rqinchli, Sarguzasht",
        "davlat": "Irlandiya va Ispaniya",
        "davomiyligi": "2 soat 15 daqiqa",
        "is_premium": False,
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
        movie.setdefault("likes", set())
        movie.setdefault("dislikes", set())
        movie.pop("is_premium", None)
        movie.setdefault("is_premiere", False)
        movie.setdefault("trailer_file_id", None)
        movie.setdefault("media_type", "video")
        movie["likes"] = set(movie.get("likes") or [])
        movie["dislikes"] = set(movie.get("dislikes") or [])


def has_premium_access(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if user_id == ADMIN_ID:
        return True
    if user_id in PREMIUM_OVERRIDES:
        return PREMIUM_OVERRIDES[user_id]
    if user_id in PREMIUM_USERS:
        return True
    expires_at = PREMIUM_SUBSCRIPTIONS.get(user_id)
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) > datetime.now()
    except ValueError:
        return False


def has_library_access(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if has_premium_access(user_id):
        return True
    expires_at = LIBRARY_SUBSCRIPTIONS.get(user_id)
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at) > datetime.now()
    except ValueError:
        return False


def grant_library_subscription(user_id: int) -> datetime:
    now = datetime.now()
    current_expiry = LIBRARY_SUBSCRIPTIONS.get(user_id)
    if current_expiry:
        try:
            now = max(now, datetime.fromisoformat(current_expiry))
        except ValueError:
            pass
    expires_at = now + timedelta(days=30)
    LIBRARY_SUBSCRIPTIONS[user_id] = expires_at.isoformat(timespec="seconds")
    return expires_at


def save_data() -> None:
    """Kinolar, foydalanuvchilar va reytinglarni restartdan keyin ham saqlaydi."""
    movies_data = {}
    for code, movie in MOVIES_DATABASE.items():
        movie_data = dict(movie)
        movie_data.pop("likes", None)
        movie_data.pop("dislikes", None)
        movie_data.pop("is_premium", None)
        movies_data[code] = movie_data
    data = {
        "movies": movies_data,
        "premium_users": list(dict.fromkeys(PREMIUM_USERS)),
        "premium_subscriptions": {str(k): v for k, v in PREMIUM_SUBSCRIPTIONS.items()},
        "premium_overrides": {str(k): v for k, v in PREMIUM_OVERRIDES.items()},
        "bot_settings": {
            **BOT_SETTINGS,
            "premium_prices": {
                code: int(plan["price"]) for code, plan in PREMIUM_PLANS.items()
            },
        },
        "pending_premium_payments": PENDING_PREMIUM_PAYMENTS,
        "library_subscriptions": {str(k): v for k, v in LIBRARY_SUBSCRIPTIONS.items()},
        "pending_library_payments": PENDING_LIBRARY_PAYMENTS,
        "all_users": list(ALL_USERS),
        "instagram_confirmed_users": list(INSTAGRAM_CONFIRMED_USERS),
        "user_info": {str(k): v for k, v in USER_INFO.items()},
        "favorites": {str(k): list(v) for k, v in FAVORITES.items()},
        "watch_later": {str(k): list(v) for k, v in WATCH_LATER.items()},
        "library_history": {str(k): v for k, v in LIBRARY_HISTORY.items()},
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
            "premium": has_premium_access(user_id),
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
        apply_bot_settings(data.get("bot_settings", {}))
        if not PREMIUM_USERS_CONFIGURED:
            PREMIUM_USERS[:] = list(dict.fromkeys(
                PREMIUM_USERS + [int(user_id) for user_id in data.get("premium_users", [])]
            ))
        PREMIUM_SUBSCRIPTIONS.update({
            int(user_id): str(expires_at)
            for user_id, expires_at in data.get("premium_subscriptions", {}).items()
        })
        PREMIUM_OVERRIDES.update({
            int(user_id): bool(is_premium)
            for user_id, is_premium in data.get("premium_overrides", {}).items()
        })
        PENDING_PREMIUM_PAYMENTS.update({
            str(payment_id): payment
            for payment_id, payment in data.get("pending_premium_payments", {}).items()
            if isinstance(payment, dict)
        })
        LIBRARY_SUBSCRIPTIONS.update({
            int(user_id): str(expires_at)
            for user_id, expires_at in data.get("library_subscriptions", {}).items()
        })
        PENDING_LIBRARY_PAYMENTS.update({
            str(payment_id): payment
            for payment_id, payment in data.get("pending_library_payments", {}).items()
            if isinstance(payment, dict)
        })
        ALL_USERS.update(int(user_id) for user_id in data.get("all_users", []))
        INSTAGRAM_CONFIRMED_USERS.update(
            int(user_id) for user_id in data.get("instagram_confirmed_users", [])
        )
        USER_INFO.update({int(k): v for k, v in data.get("user_info", {}).items()})
        FAVORITES.update({int(k): set(v) for k, v in data.get("favorites", {}).items()})
        WATCH_LATER.update({int(k): set(v) for k, v in data.get("watch_later", {}).items()})
        LIBRARY_HISTORY.update({
            int(k): [entry for entry in v if isinstance(entry, dict)]
            for k, v in data.get("library_history", {}).items()
            if isinstance(v, list)
        })
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
                MOVIES_DATABASE[str(code)].setdefault("media_type", "video")
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
    else:
        # Username yoki ism keyinchalik o'zgarsa, bazada eski profil qolib ketmasin.
        USER_INFO[user.id].update(
            {
                "name": user.full_name or USER_INFO[user.id].get("name", "Noma'lum"),
                "username": f"@{user.username}" if user.username else "Mavjud emas",
            }
        )
    save_data()
    return is_new


def get_callback_message(call: CallbackQuery) -> Message | None:
    """Callback xabarini faqat tahrirlash mumkin bo'lsa qaytaradi."""
    return call.message if isinstance(call.message, Message) else None


def has_instagram_access(user_id: int | None) -> bool:
    return (
        user_id == ADMIN_ID
        or not BOT_SETTINGS["instagram_required"]
        or user_id in INSTAGRAM_CONFIRMED_USERS
    )


def instagram_subscription_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(
                text=f"📷 @{username}",
                url=f"https://www.instagram.com/{username}/",
            )
        ]
        for username in INSTAGRAM_ACCOUNTS
    ]
    buttons.append([InlineKeyboardButton(text="💎 Premium", callback_data="premium_info")])
    buttons.append([
        InlineKeyboardButton(text="✅ Obuna bo'ldim", callback_data="instagram_confirmed")
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def instagram_subscription_text() -> str:
    accounts = "\n".join(
        f"{index}. {escape(username)}"
        for index, username in enumerate(INSTAGRAM_ACCOUNTS, 1)
    )
    return (
        "📷 <b>Botdan foydalanish uchun Instagram sahifalarimizga obuna bo'ling:</b>\n\n"
        f"{accounts}\n\n"
        "Barcha sahifalarga obuna bo'lgach, quyidagi tugmani bosing."
    )


def format_duration(davomiyligi: str) -> str:
    match = re.match(r"\s*(\d+)\s*soat\s*(\d+)\s*minut", davomiyligi)
    if match:
        return f"{match.group(1)} soat {match.group(2)} daqiqa"
    return davomiyligi.strip()


def build_caption(code: str, movie: dict) -> str:
    premiere_badge = "🎬 <b>PREMYERA!</b>\n" if movie.get("is_premiere") else ""
    lines = [
        f"{premiere_badge}🎬 <b>{escape(str(movie['name']))}</b>",
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
    ]
    return "\n".join(lines)


def grant_premium_subscription(user_id: int, plan_code: str) -> datetime:
    plan = PREMIUM_PLANS[plan_code]
    now = datetime.now()
    current_expiry = PREMIUM_SUBSCRIPTIONS.get(user_id)
    if current_expiry:
        try:
            now = max(now, datetime.fromisoformat(current_expiry))
        except ValueError:
            pass
    expires_at = now + plan["duration"]
    PREMIUM_SUBSCRIPTIONS[user_id] = expires_at.isoformat(timespec="seconds")
    return expires_at


def today_str() -> str:
    return date.today().isoformat()


def get_remaining_free_views(user_id: int | None) -> int:
    """Return remaining daily free views, or -1 when views are unlimited."""
    if DAILY_FREE_LIMIT == 0:
        return -1
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


def active_premium_user_ids() -> set[int]:
    return {
        user_id
        for user_id in set(PREMIUM_USERS) | set(PREMIUM_SUBSCRIPTIONS)
        if has_premium_access(user_id)
    }


def premium_offer_text(user_id: int | None = None) -> str:
    status = ""
    expires_at = PREMIUM_SUBSCRIPTIONS.get(user_id) if user_id is not None else None
    if has_premium_access(user_id):
        if expires_at:
            try:
                expiry_label = datetime.fromisoformat(expires_at).strftime("%d.%m.%Y %H:%M")
                status = f"\n\n✅ Premium faol. Tugash vaqti: <b>{expiry_label}</b>"
            except ValueError:
                status = "\n\n✅ Premium faol."
        else:
            status = "\n\n✅ Premium faol."
    return (
        "💎 <b>Gold Cinema Premium</b>\n\n"
        "Barcha foydalanuvchilar kinolarni cheklovsiz tomosha qilishi mumkin.\n"
        "Premium bilan qo'shimcha imkoniyatlarga ega bo'lasiz, jumladan shaxsiy kino kutubxonasiga!"
        f"{status}\n\n"
        "👇 O'zingizga mos tarifni tanlang:"
    )


def build_movie_keyboard(code: str, movie: dict, user_id: int | None = None) -> InlineKeyboardMarkup:
    likes = len(movie["likes"])
    dislikes = len(movie["dislikes"])
    library_access = has_library_access(user_id)
    is_fav = library_access and code in FAVORITES.get(user_id, set())
    is_later = library_access and code in WATCH_LATER.get(user_id, set())
    fav_text = ("💛 Saqlangan" if is_fav else "⭐ Sevimliga") if library_access else "🔒 Sevimlilar"
    later_text = ("🕒 Keyinroq saqlangan" if is_later else "🕒 Keyinroq") if library_access else "🔒 Keyinroq"

    keyboard = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"like:{code}"),
            InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"dislike:{code}"),
        ],
        [
            InlineKeyboardButton(text=fav_text, callback_data=f"fav:{code}"),
            InlineKeyboardButton(text=later_text, callback_data=f"later:{code}"),
        ],
        [InlineKeyboardButton(text="🔄 Boshqa kino", callback_data="menu_rand")],
        [InlineKeyboardButton(text="🧭 Bosh menyu", callback_data="menu_home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


def build_admin_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Statistika"), KeyboardButton(text="👥 Foydalanuvchilar")],
            [KeyboardButton(text="🎬 Kino qo'shish"), KeyboardButton(text="🗑 Kino o'chirish")],
            [KeyboardButton(text="💎 Premium berish"), KeyboardButton(text="🚫 Premium olish")],
            [KeyboardButton(text="📥 Kino buyurtmalari"), KeyboardButton(text="💰 To'lovlar")],
            [KeyboardButton(text="🎁 Promo-kodlar"), KeyboardButton(text="📢 Reklama yuborish")],
            [KeyboardButton(text="👥 Referallar"), KeyboardButton(text="🏆 Taklif qilganlar")],
            [KeyboardButton(text="📚 Kinolar ro'yxati"), KeyboardButton(text="👤 Foydalanuvchi paneli")],
        ],
        is_persistent=True,
        one_time_keyboard=False,
        input_field_placeholder="Admin panel tugmalarini tanlang",
        resize_keyboard=True,
    )


def build_user_reply_keyboard(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Foydalanuvchi uchun so'ralgan 2 ustunli boshqaruv paneli."""
    keyboard = [
        [KeyboardButton(text="🔎 Kino qidirish"), KeyboardButton(text="🔥 Yangi kinolar")],
        [KeyboardButton(text="⭐ Premium"), KeyboardButton(text="🎁 Premium sovg'a qilish")],
        [KeyboardButton(text="📥 Kino buyurtma qilish"), KeyboardButton(text="❤️ Sevimlilar")],
        [KeyboardButton(text="📜 Kino tarixi"), KeyboardButton(text="👤 Mening profilim")],
        [KeyboardButton(text="💎 VIP"), KeyboardButton(text="👥 Referal")],
    ]
    if is_admin:
        keyboard.append([
            KeyboardButton(text="📞 Yordam"),
            KeyboardButton(text="👑 Admin panel"),
        ])
    else:
        keyboard.append([KeyboardButton(text="📞 Yordam")])
    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def find_movie_matches(query: str) -> dict:
    query = query.strip().casefold()
    if not query:
        return {}
    return {
        code: m
        for code, m in MOVIES_DATABASE.items()
        if any(
            query in str(m.get(field, "")).casefold()
            for field in ("name", "janr", "davlat", "til", "yil", "sifat")
        )
    }


def movie_code_sort_key(code: str) -> tuple[int, int | str]:
    """Sort numeric movie codes first while supporting custom codes safely."""
    return (0, int(code)) if str(code).isdigit() else (1, str(code).lower())


def build_results_text(title: str, matches: dict) -> str:
    text = f"{title}\n\n"
    for code in sorted(matches, key=movie_code_sort_key):
        movie = matches[code]
        line = (
            f"🎬 <b>{escape(str(movie.get('name', 'Nomsiz')))}</b> — "
            f"kodi: <code>{escape(str(code))}</code> "
            f"({escape(str(movie.get('yil', 'Noma\'lum')))})\n"
        )
        if len(text) + len(line) > 3800:
            text += "\n⚠️ <i>Natijalar ko'pligi sababli ro'yxat qisqartirildi.</i>"
            break
        text += line
    text += "\n👇 <i>Kino ko'rish uchun uning kodini chatga yuboring!</i>"
    return text


def library_offer_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Kutubxonani ulash — {LIBRARY_PRICE}", callback_data="library_subscribe")],
        [InlineKeyboardButton(text="💎 Premium tariflari", callback_data="premium_info")],
    ])


def library_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ Sevimli filmlar", callback_data="library_view:favorites"),
            InlineKeyboardButton(text="🕒 Keyinroq", callback_data="library_view:later"),
        ],
        [
            InlineKeyboardButton(text="✅ Ko'rish tarixi", callback_data="library_view:history"),
            InlineKeyboardButton(text="🎯 Tavsiyalar", callback_data="library_view:recommendations"),
        ],
        [InlineKeyboardButton(text="🧭 Bosh menyu", callback_data="menu_home")],
    ])


def library_later_keyboard(codes: list[str]) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            text=f"🗑 Olib tashlash: {MOVIES_DATABASE[code]['name'][:35]}",
            callback_data=f"library_remove_later:{code}",
        )]
        for code in codes
        if code in MOVIES_DATABASE
    ]
    buttons.append([InlineKeyboardButton(text="◀️ Kutubxona", callback_data="menu_library")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_personal_recommendations(user_id: int) -> dict:
    preferences: dict[str, int] = {}
    seed_codes = set(FAVORITES.get(user_id, set()))
    seed_codes.update(
        str(entry.get("code"))
        for entry in LIBRARY_HISTORY.get(user_id, [])
        if entry.get("code")
    )
    seed_codes.update(
        code for code, movie in MOVIES_DATABASE.items()
        if user_id in movie.get("likes", set())
    )
    for code in seed_codes:
        movie = MOVIES_DATABASE.get(code)
        if not movie:
            continue
        weight = 2 if code in FAVORITES.get(user_id, set()) else 1
        if user_id in movie.get("likes", set()):
            weight += 1
        for genre in re.split(r"[,/|]+", str(movie.get("janr", ""))):
            genre = genre.strip().casefold()
            if genre:
                preferences[genre] = preferences.get(genre, 0) + weight

    excluded = set(FAVORITES.get(user_id, set())) | WATCH_LATER.get(user_id, set())
    excluded.update(
        str(entry.get("code"))
        for entry in LIBRARY_HISTORY.get(user_id, [])
        if entry.get("code")
    )
    candidates = [
        (code, movie)
        for code, movie in MOVIES_DATABASE.items()
        if code not in excluded
    ]

    def score(item: tuple[str, dict]) -> tuple[int, int, tuple[int, int | str]]:
        code, movie = item
        genre_score = sum(
            preferences.get(genre.strip().casefold(), 0)
            for genre in re.split(r"[,/|]+", str(movie.get("janr", "")))
            if genre.strip()
        )
        popularity = len(movie.get("likes", set())) - len(movie.get("dislikes", set()))
        return -genre_score, -popularity, movie_code_sort_key(code)

    if not candidates:
        candidates = list(MOVIES_DATABASE.items())
    candidates.sort(key=score)
    return dict(candidates[:10])


async def send_library_offer(message: Message) -> None:
    await message.answer(
        "📚 <b>Shaxsiy kino kutubxonasi</b>\n\n"
        "⭐ Sevimli filmlar\n"
        "🕒 Keyinroq ko'rish ro'yxati\n"
        "✅ Ko'rish tarixi\n"
        "🎯 Sizga mos shaxsiy tavsiyalar\n\n"
        "Ko'rish tarixi obuna faol bo'lgan vaqtdagi kinolarni saqlaydi.\n"
        f"Obuna narxi: <b>{LIBRARY_PRICE}</b> (30 kun).\n"
        "💎 Premium foydalanuvchilar kutubxonadan qo'shimcha to'lovsiz foydalanadi.\n\n"
        "Ulash uchun tugmani bosing va to'lov chekini yuboring.",
        parse_mode="HTML",
        reply_markup=library_offer_keyboard(),
    )


async def send_library_home(message: Message, user_id: int) -> None:
    if not has_library_access(user_id):
        await send_library_offer(message)
        return
    expires_at = LIBRARY_SUBSCRIPTIONS.get(user_id)
    expiry_text = ""
    if expires_at and not has_premium_access(user_id):
        try:
            expiry_text = (
                "\nObuna tugash vaqti: "
                f"<b>{datetime.fromisoformat(expires_at).strftime('%d.%m.%Y %H:%M')}</b>"
            )
        except ValueError:
            expiry_text = ""
    await message.answer(
        "📚 <b>Shaxsiy kino kutubxonangiz</b>\n"
        "Kerakli bo'limni tanlang."
        f"{expiry_text}",
        parse_mode="HTML",
        reply_markup=library_menu_keyboard(),
    )


async def send_library_section(message: Message, user_id: int, section: str) -> None:
    if not has_library_access(user_id):
        await send_library_offer(message)
        return

    if section == "favorites":
        codes = sorted(
            (code for code in FAVORITES.get(user_id, set()) if code in MOVIES_DATABASE),
            key=movie_code_sort_key,
        )
        matches = {code: MOVIES_DATABASE[code] for code in codes}
        text = (
            build_results_text("⭐ <b>Sevimli filmlaringiz:</b>", matches)
            if matches else "⭐ Sevimlilar ro'yxatingiz hali bo'sh."
        )
        await message.answer(text, parse_mode="HTML")
        return

    if section == "later":
        codes = sorted(
            (code for code in WATCH_LATER.get(user_id, set()) if code in MOVIES_DATABASE),
            key=movie_code_sort_key,
        )
        matches = {code: MOVIES_DATABASE[code] for code in codes}
        if not codes:
            await message.answer("🕒 Keyinroq ko'rish ro'yxatingiz bo'sh.")
            return
        await message.answer(
            build_results_text("🕒 <b>Keyinroq ko'rish ro'yxati:</b>", matches),
            parse_mode="HTML",
            reply_markup=library_later_keyboard(codes[:20]),
        )
        return

    if section == "history":
        entries = [
            entry for entry in reversed(LIBRARY_HISTORY.get(user_id, []))
            if str(entry.get("code", "")) in MOVIES_DATABASE
        ][:20]
        if not entries:
            await message.answer("✅ Hali ko'rish tarixingiz yo'q. Kino ko'rsangiz, bu yerda saqlanadi.")
            return
        lines = ["✅ <b>Oxirgi ko'rilgan kinolar:</b>\n"]
        for index, entry in enumerate(entries, 1):
            code = str(entry["code"])
            movie = MOVIES_DATABASE[code]
            watched_at = str(entry.get("watched_at", ""))
            try:
                watched_label = datetime.fromisoformat(watched_at).strftime("%d.%m.%Y %H:%M")
            except ValueError:
                watched_label = "sana noma'lum"
            lines.append(
                f"{index}. <b>{escape(str(movie.get('name', 'Nomsiz')))}</b> — "
                f"{watched_label} | kodi: <code>{escape(code)}</code>"
            )
        await message.answer("\n".join(lines), parse_mode="HTML")
        return

    if section == "recommendations":
        matches = get_personal_recommendations(user_id)
        if not matches:
            await message.answer("🎯 Hozircha tavsiya uchun kinolar topilmadi.")
            return
        lines = ["🎯 <b>Sizga mos tavsiyalar:</b>\n"]
        for index, (code, movie) in enumerate(matches.items(), 1):
            year = escape(str(movie.get("yil", "Noma'lum")))
            lines.append(
                f"{index}. <b>{escape(str(movie.get('name', 'Nomsiz')))}</b> — "
                f"{year} | "
                f"kodi: <code>{escape(str(code))}</code>"
            )
        lines.append("\n👇 <i>Kino ko'rish uchun uning kodini chatga yuboring!</i>")
        await message.answer(
            "\n".join(lines),
            parse_mode="HTML",
        )
        return

    await message.answer("⚠️ Kutubxona bo'limi topilmadi.")


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
            "Kerakli amalni pastki paneldan tanlang:",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
        return

    if not BOT_SETTINGS["instagram_required"] or message.from_user.id in INSTAGRAM_CONFIRMED_USERS:
        await message.answer(
            f"👋 <b>Xush kelibsiz, {escape(message.from_user.full_name)}!</b>\n"
            "Kerakli bo'limni pastki menyudan tanlang:",
            parse_mode="HTML",
            reply_markup=build_user_reply_keyboard(),
        )
        return

    await message.answer(
        instagram_subscription_text(),
        parse_mode="HTML",
        reply_markup=instagram_subscription_keyboard(),
    )


@dp.callback_query(F.data == "instagram_confirmed")
async def instagram_subscription_confirmed(call: CallbackQuery):
    if call.from_user.id == ADMIN_ID:
        await call.answer("✅ Admin uchun obuna tekshiruvi kerak emas.")
        return
    INSTAGRAM_CONFIRMED_USERS.add(call.from_user.id)
    save_data()
    await call.answer("✅ Obuna tasdiqlandi!")
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            "✅ Rahmat! Endi Gold Cinema botidan foydalanishingiz mumkin. "
            "Kerakli bo'limni pastki menyudan tanlang.",
            reply_markup=None,
        )
        await message.answer(
            "🎬 Foydalanuvchi paneli:",
            reply_markup=build_user_reply_keyboard(),
        )


@dp.message(F.text == "👑 Admin panel")
async def admin_panel_msg(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer(
        "👑 <b>ADMIN PANEL</b>\nKerakli amalni pastki paneldan tanlang:",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "👤 Foydalanuvchi paneli")
async def user_panel_msg(message: Message):
    if message.from_user is None:
        return
    await message.answer(
        "🎬 <b>Foydalanuvchi paneli</b>\nKerakli bo'limni pastki menyudan tanlang:",
        parse_mode="HTML",
        reply_markup=build_user_reply_keyboard(message.from_user.id == ADMIN_ID),
    )


@dp.callback_query(F.data == "user_panel")
async def user_panel_callback(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    await message.answer(
        "🎬 <b>Foydalanuvchi paneli</b>\nKerakli bo'limni pastki menyudan tanlang:",
        parse_mode="HTML",
        reply_markup=build_user_reply_keyboard(call.from_user.id == ADMIN_ID),
    )


@dp.callback_query(F.data == "admin_panel")
async def admin_panel_callback(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            "👑 <b>ADMIN PANEL</b>\nKerakli amalni pastki paneldan tanlang:",
            parse_mode="HTML",
            reply_markup=None,
        )
        await message.answer(
            "👑 Admin panel:",
            reply_markup=build_admin_reply_keyboard(),
        )


@dp.message(
    F.text.in_({
        "📊 Statistika",
        "👥 Foydalanuvchilar",
        "🎬 Kino qo'shish",
        "🗑 Kino o'chirish",
        "💎 Premium berish",
        "🚫 Premium olish",
        "📥 Kino buyurtmalari",
        "💰 To'lovlar",
        "🎁 Promo-kodlar",
        "👥 Referallar",
        "🏆 Taklif qilganlar",
        "📢 Reklama yuborish",
        "📚 Kinolar ro'yxati",
    }),
)
async def admin_reply_panel_action(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return

    action = message.text
    await state.clear()
    if action == "📊 Statistika":
        total_views = sum(VIEWS.values())
        total_likes = sum(len(movie["likes"]) for movie in MOVIES_DATABASE.values())
        total_referrals = sum(len(users) for users in REFERRALS.values())
        await message.answer(
            "📊 <b>Bot statistikasi</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{len(ALL_USERS)}</b>\n"
            f"💎 Premium foydalanuvchilar: <b>{len(active_premium_user_ids())}</b>\n"
            f"🤝 Takliflar: <b>{total_referrals}</b>\n"
            f"🎬 Kinolar: <b>{len(MOVIES_DATABASE)}</b>\n"
            f"👁 Ko'rishlar: <b>{total_views}</b>\n"
            f"👍 Like'lar: <b>{total_likes}</b>",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "👥 Foydalanuvchilar":
        await admin_users_msg(message)
    elif action == "🎬 Kino qo'shish":
        await start_movie_add(message, state)
    elif action == "🗑 Kino o'chirish":
        await state.set_state(DeleteMovie.code)
        await message.answer(
            "🗑 O'chiriladigan kino kodini yuboring:\nBekor qilish uchun /cancel yuboring."
        )
    elif action in {"💎 Premium berish", "🚫 Premium olish"}:
        premium_action = "grant" if action == "💎 Premium berish" else "revoke"
        await state.update_data(premium_action=premium_action)
        await state.set_state(AdminPremium.user_id)
        instruction = "beriladigan" if premium_action == "grant" else "olinadigan"
        await message.answer(
            f"{action} uchun foydalanuvchining Telegram ID sini yuboring "
            f"(Premium {instruction} foydalanuvchi)."
        )
    elif action == "📥 Kino buyurtmalari":
        await message.answer(
            "📥 <b>Kino buyurtmalari</b>\n\n"
            "Yangi buyurtmalar admin chatiga foydalanuvchi va kino nomi bilan yuboriladi. "
            "Alohida buyurtmalar navbati hozircha yo'q.",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "💰 To'lovlar":
        await message.answer(
            "💰 <b>Kutilayotgan to'lovlar</b>\n\n"
            f"⭐ Premium cheklar: <b>{len(PENDING_PREMIUM_PAYMENTS)}</b>\n"
            f"💎 VIP cheklar: <b>{len(PENDING_LIBRARY_PAYMENTS)}</b>\n\n"
            "Tasdiqlash yoki rad etish uchun chek xabaridagi tugmalardan foydalaning.",
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "🎁 Promo-kodlar":
        await message.answer(
            "🎁 Promo-kodlar tizimi hozircha sozlanmagan.",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "👥 Referallar":
        ranked_users = sorted(
            ALL_USERS,
            key=lambda user_id: (-len(REFERRALS.get(user_id, set())), user_id),
        )
        total_referrals = sum(len(REFERRALS.get(user_id, set())) for user_id in ALL_USERS)
        lines = [
            "👥 <b>Referallar hisoboti</b>\n\n",
            f"Jami taklif orqali kelganlar: <b>{total_referrals}</b>\n\n",
        ]
        for index, user_id in enumerate(ranked_users, 1):
            info = USER_INFO.get(user_id, {})
            name = escape(str(info.get("name", "Noma'lum")))
            line = (
                f"{index}. <b>{name}</b> — "
                f"{len(REFERRALS.get(user_id, set()))} ta | <code>{user_id}</code>\n"
            )
            if sum(map(len, lines)) + len(line) > 3800:
                lines.append("\n⚠️ Ro'yxat uzunligi sababli qisqartirildi.")
                break
            lines.append(line)
        await message.answer(
            "".join(lines),
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "🏆 Taklif qilganlar":
        inviters = sorted(
            (
                (user_id, len(REFERRALS.get(user_id, set())))
                for user_id in ALL_USERS
                if REFERRALS.get(user_id)
            ),
            key=lambda item: (-item[1], item[0]),
        )
        total_invited = sum(count for _, count in inviters)
        lines = [
            "🏆 <b>Do'st taklif qilgan foydalanuvchilar</b>\n\n",
            f"Taklif qilganlar: <b>{len(inviters)}</b> ta | "
            f"Jami takliflar: <b>{total_invited}</b>\n\n",
        ]
        for index, (user_id, count) in enumerate(inviters, 1):
            info = USER_INFO.get(user_id, {})
            name = escape(str(info.get("name", "Noma'lum")))
            username = escape(str(info.get("username", "Mavjud emas")))
            premium_status = "💎 Premium" if has_premium_access(user_id) else "🆓 Bepul"
            line = (
                f"{index}. <b>{name}</b> — <b>{count}</b> ta taklif | {premium_status}\n"
                f"├ Username: {username}\n"
                f"└ ID: <code>{user_id}</code>\n"
            )
            if sum(map(len, lines)) + len(line) > 3800:
                lines.append("\n⚠️ Ro'yxat uzunligi sababli qisqartirildi.")
                break
            lines.append(line)
        if not inviters:
            lines.append("Hozircha do'st taklif qilgan foydalanuvchilar yo'q.")
        lines.append(
            "\nPremium berish uchun ID ni oling, so'ng "
            "💎 Premium berish tugmasidan foydalaning."
        )
        await message.answer(
            "".join(lines),
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )
    elif action == "📢 Reklama yuborish":
        await state.set_state(BroadcastState.message)
        await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:")
    elif action == "📚 Kinolar ro'yxati":
        await message.answer(
            build_movie_admin_list(),
            parse_mode="HTML",
            reply_markup=build_admin_reply_keyboard(),
        )


@dp.callback_query(F.data.startswith("admin_setting:"))
async def admin_setting_action(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID or not call.data:
        await call.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    await state.clear()
    setting = call.data.removeprefix("admin_setting:")
    if setting == "toggle_subscription":
        BOT_SETTINGS["instagram_required"] = not BOT_SETTINGS["instagram_required"]
        save_data()
        await call.answer(
            "✅ Obuna talabi " +
            ("yoqildi." if BOT_SETTINGS["instagram_required"] else "o'chirildi.")
        )
        message = get_callback_message(call)
        if message:
            await message.edit_text(
                admin_settings_text(),
                parse_mode="HTML",
                reply_markup=admin_settings_keyboard(),
            )
        return
    else:
        prompts = {
            "card": (
                "💳 Karta raqami va egasini bitta qatorda yuboring:\n"
                "<code>8600 0000 0000 0000 | Ism Familiya</code>"
            ),
            "accounts": (
                "📷 Instagram username'larini vergul bilan ajratib yuboring "
                "(masalan: <code>account_one, account_two</code>)."
            ),
            "limit": (
                "🎬 Kunlik bepul kino limitini raqamda yuboring.\n"
                "<code>0</code> — cheksiz, masalan <code>5</code> — kuniga 5 ta."
            ),
            "library_price": "📚 Kutubxonaning oylik narxini so'mda yuboring (faqat raqam).",
        }
        if setting.startswith("premium:"):
            plan_code = setting.split(":", 1)[1]
            if plan_code not in PREMIUM_PLANS:
                await call.answer("❌ Premium tarifi topilmadi.", show_alert=True)
                return
            setting = f"premium:{plan_code}"
            prompts[setting] = (
                f"💎 {PREMIUM_PLANS[plan_code]['period']} Premium narxini so'mda yuboring "
                "(faqat raqam)."
            )
        prompt = prompts.get(setting)
        if prompt is None:
            await call.answer("❌ Sozlama topilmadi.", show_alert=True)
            return
        await state.update_data(settings_key=setting)
        await state.set_state(AdminSettings.value)
        await call.answer()
        message = get_callback_message(call)
        if message:
            await message.answer(prompt, parse_mode="HTML")
            return

    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            admin_settings_text(),
            parse_mode="HTML",
            reply_markup=admin_settings_keyboard(),
        )


@dp.message(AdminSettings.value, F.text)
async def admin_setting_value(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    state_data = await state.get_data()
    setting = state_data.get("settings_key")
    value = message.text.strip()
    if setting == "card":
        parts = value.split("|", 1)
        if len(parts) != 2:
            await message.answer("⚠️ Karta raqami va egasini <code>raqam | ism</code> ko'rinishida yuboring.", parse_mode="HTML")
            return
        card_number, card_name = (part.strip() for part in parts)
        normalized_card = card_number.replace(" ", "").replace("-", "")
        if not normalized_card.isdigit() or not 12 <= len(normalized_card) <= 19 or not card_name:
            await message.answer("⚠️ Karta raqamini tekshiring (12–19 raqam) va egasining ismini kiriting.")
            return
        BOT_SETTINGS["card_number"] = card_number
        BOT_SETTINGS["card_name"] = card_name
    elif setting == "accounts":
        accounts = [item.strip().lstrip("@") for item in value.split(",") if item.strip()]
        if not accounts or any(not re.fullmatch(r"[A-Za-z0-9._]{1,30}", item) for item in accounts):
            await message.answer("⚠️ Kamida bitta to'g'ri Instagram username yuboring; @ va vergul ishlatish mumkin.")
            return
        BOT_SETTINGS["instagram_accounts"] = accounts
    elif setting == "limit":
        if not value.isdigit() or int(value) > 10000:
            await message.answer("⚠️ Limit 0 dan 10000 gacha bo'lgan butun son bo'lishi kerak.")
            return
        BOT_SETTINGS["daily_free_limit"] = int(value)
    elif setting == "library_price" or (isinstance(setting, str) and setting.startswith("premium:")):
        normalized_price = value.replace(" ", "").replace(",", "").replace(".", "")
        if not normalized_price.isdigit() or int(normalized_price) > 1_000_000_000:
            await message.answer("⚠️ Narxni 0 dan 1 000 000 000 gacha raqam bilan yuboring.")
            return
        amount = int(normalized_price)
        if setting == "library_price":
            BOT_SETTINGS["library_price"] = amount
        else:
            plan_code = setting.split(":", 1)[1]
            if plan_code not in PREMIUM_PLANS:
                await state.clear()
                await message.answer("❌ Premium tarifi topilmadi. Sozlamani qayta oching.")
                return
            BOT_SETTINGS["premium_prices"][plan_code] = amount
    else:
        await state.clear()
        await message.answer("❌ Sozlama topilmadi. Sozlamalar bo'limini qayta oching.")
        return

    apply_bot_settings(BOT_SETTINGS)
    save_data()
    await state.clear()
    await message.answer(
        "✅ Sozlama saqlandi.\n\n" + admin_settings_text(),
        parse_mode="HTML",
        reply_markup=admin_settings_keyboard(),
    )


@dp.callback_query(F.data == "premium_info")
async def premium_info(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(
            premium_offer_text(call.from_user.id),
            parse_mode="HTML",
            reply_markup=premium_plans_keyboard(),
        )


@dp.message(F.text.in_({"💎 Premium", "⭐ Premium"}))
async def premium_info_msg(message: Message):
    if message.from_user is None:
        return
    register_user(message.from_user)
    await message.answer(
        premium_offer_text(message.from_user.id),
        parse_mode="HTML",
        reply_markup=premium_plans_keyboard(),
    )


@dp.callback_query(F.data == "gift_premium")
async def gift_premium_start(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(GiftPremiumState.recipient_id)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer(
            "🎁 Premium sovg'a qilmoqchi bo'lgan foydalanuvchining Telegram ID sini yuboring.\n"
            "Qabul qiluvchi avval botni ishga tushirgan bo'lishi kerak."
        )


@dp.message(F.text == "🎁 Premium sovg'a qilish")
async def gift_premium_start_msg(message: Message, state: FSMContext):
    if message.from_user is None:
        return
    await state.clear()
    await state.set_state(GiftPremiumState.recipient_id)
    await message.answer(
        "🎁 Premium sovg'a qilmoqchi bo'lgan foydalanuvchining Telegram ID sini yuboring.\n"
        "Qabul qiluvchi avval botni ishga tushirgan bo'lishi kerak."
    )


@dp.message(GiftPremiumState.recipient_id, F.text)
async def gift_premium_recipient(message: Message, state: FSMContext):
    if message.from_user is None or message.text is None:
        return
    raw_id = message.text.strip()
    if not raw_id.isdigit() or int(raw_id) <= 0:
        await message.answer("⚠️ Telegram ID faqat musbat raqamlardan iborat bo'lishi kerak.")
        return
    recipient_id = int(raw_id)
    if recipient_id == message.from_user.id:
        await message.answer("🎁 O'zingizga sovg'a yuborib bo'lmaydi. Boshqa foydalanuvchi ID sini kiriting.")
        return
    if recipient_id not in ALL_USERS:
        await message.answer("⚠️ Bu foydalanuvchi botni hali ishga tushirmagan. Avval botga /start yuborishi kerak.")
        return
    await state.update_data(gift_recipient_id=recipient_id)
    await message.answer(
        "🎁 <b>Premium sovg'a tarifi:</b>\nKerakli muddatni tanlang:",
        parse_mode="HTML",
        reply_markup=gift_premium_plans_keyboard(),
    )


@dp.callback_query(F.data.startswith("gift_plan:"))
async def gift_premium_plan_selected(call: CallbackQuery, state: FSMContext):
    if not call.data:
        await call.answer("❌ Tarif topilmadi.", show_alert=True)
        return
    plan_code = call.data.split(":", 1)[1]
    plan = PREMIUM_PLANS.get(plan_code)
    data = await state.get_data()
    recipient_id = data.get("gift_recipient_id")
    if plan is None or not isinstance(recipient_id, int) or recipient_id not in ALL_USERS:
        await call.answer("⚠️ Sovg'a ma'lumoti topilmadi. Jarayonni boshidan boshlang.", show_alert=True)
        await state.clear()
        return
    if not CARD_NUMBER or ADMIN_ID == 0:
        await call.answer("⚠️ To'lov ma'lumotlari sozlanmagan.", show_alert=True)
        return
    await state.set_state(PremiumPaymentState.waiting_receipt)
    await state.update_data(
        plan=premium_plan_label(plan_code),
        plan_code=plan_code,
        gift_recipient_id=recipient_id,
    )
    await call.answer("✅ Tarif tanlandi!")
    message = get_callback_message(call)
    if message:
        card_name = CARD_NAME or "Ko'rsatilmagan"
        await message.answer(
            f"🎁 <b>Tanlangan sovg'a tarifi:</b> {escape(premium_plan_label(plan_code))}\n\n"
            f"💳 <b>Karta raqami:</b> <code>{escape(CARD_NUMBER)}</code>\n"
            f"👤 <b>Karta egasi:</b> {escape(card_name)}\n\n"
            "To'lovdan so'ng chek rasmini yoki faylini yuboring. "
            "Admin tasdiqlagach, Premium qabul qiluvchiga beriladi.",
            parse_mode="HTML",
        )


@dp.callback_query(F.data.startswith("premium_plan:"))
async def premium_plan_selected(call: CallbackQuery, state: FSMContext):
    if not call.data:
        await call.answer("❌ Tarif topilmadi.", show_alert=True)
        return
    plan_code = call.data.split(":", 1)[1]
    plan = PREMIUM_PLANS.get(plan_code)
    if not plan:
        await call.answer("❌ Tarif topilmadi.", show_alert=True)
        return
    if not CARD_NUMBER or ADMIN_ID == 0:
        await call.answer("⚠️ To'lov ma'lumotlari sozlanmagan.", show_alert=True)
        return
    await state.clear()
    await state.set_state(PremiumPaymentState.waiting_receipt)
    await state.update_data(plan=premium_plan_label(plan_code), plan_code=plan_code)
    await call.answer("✅ Tarif tanlandi!")
    message = get_callback_message(call)
    if message:
        card_number = CARD_NUMBER or "Karta raqami sozlanmagan"
        card_name = CARD_NAME or "Karta egasi ko'rsatilmagan"
        await message.answer(
            f"💎 <b>Tanlangan tarif:</b> {premium_plan_label(plan_code)}\n\n"
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
    if message.from_user.id == ADMIN_ID:
        await state.clear()
        await message.answer("✅ Siz adminsiz. To'lov cheki kerak emas.")
        return
    data = await state.get_data()
    plan_name = data.get("plan", "Noma'lum tarif")
    plan_code = data.get("plan_code")
    if plan_code not in PREMIUM_PLANS:
        await state.clear()
        await message.answer("⚠️ Tarif ma'lumoti topilmadi. Xaridni qaytadan boshlang.")
        return
    user = message.from_user
    username = f"@{user.username}" if user.username else "Username mavjud emas"
    payment_id = uuid4().hex[:12]
    PENDING_PREMIUM_PAYMENTS[payment_id] = {
        "user_id": user.id,
        "plan_code": plan_code,
        "plan": str(plan_name),
        "gift_recipient_id": data.get("gift_recipient_id"),
    }
    save_data()
    review_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"premiumapprove:{payment_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"premiumreject:{payment_id}"),
    ]])
    admin_caption = (
        "💎 <b>Yangi Premium to'lov cheki</b>\n\n"
        f"📦 Tarif: <b>{escape(str(plan_name))}</b>\n"
        f"👤 Foydalanuvchi: <b>{escape(user.full_name)}</b>\n"
        f"🔗 Username: {escape(username)}\n"
        f"🆔 ID: <code>{user.id}</code>"
        + (
            f"\n🎁 Qabul qiluvchi ID: <code>{int(data['gift_recipient_id'])}</code>"
            if data.get("gift_recipient_id") is not None
            else ""
        )
    )
    try:
        if message.photo:
            await bot.send_photo(
                ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=review_keyboard,
            )
        elif message.document:
            await bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=review_keyboard,
            )
        else:
            return
    except (TelegramBadRequest, TelegramForbiddenError):
        PENDING_PREMIUM_PAYMENTS.pop(payment_id, None)
        save_data()
        await message.answer("⚠️ Chekni adminga yuborishda xatolik yuz berdi. Admin bilan bog'laning.")
        return
    await state.clear()
    await message.answer(
        "✅ Chekingiz adminga yuborildi. "
        "To'lov tasdiqlangach Premium faollashadi yoki sovg'a qabul qiluvchiga beriladi.",
        reply_markup=build_user_reply_keyboard(),
    )


@dp.callback_query(F.data.startswith("premiumapprove:"))
async def approve_premium_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID or not call.data:
        await call.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    payment_id = call.data.split(":", 1)[1]
    payment = PENDING_PREMIUM_PAYMENTS.pop(payment_id, None)
    if not payment:
        await call.answer("Chek topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    try:
        user_id = int(payment["user_id"])
        recipient_id = int(payment.get("gift_recipient_id") or user_id)
        plan_code = str(payment["plan_code"])
        if plan_code not in PREMIUM_PLANS:
            raise ValueError("Noma'lum Premium tarifi")
    except (KeyError, TypeError, ValueError):
        save_data()
        await call.answer("Chek ma'lumotlari noto'g'ri.", show_alert=True)
        return

    expires_at = grant_premium_subscription(recipient_id, plan_code)
    save_data()
    activation_text = (
        "🎁 Sizga Premium sovg'a qilindi! Gold Cinema Premium faollashtirildi.\n"
        if recipient_id != user_id
        else "✅ To'lovingiz tasdiqlandi! Gold Cinema Premium faollashtirildi.\n"
    )
    activation_text += (
        f"📦 Tarif: {escape(str(payment.get('plan', premium_plan_label(plan_code))))}\n"
        f"⏳ Amal qilish muddati: <b>{expires_at.strftime('%d.%m.%Y %H:%M')}</b>"
    )
    try:
        await bot.send_message(
            recipient_id,
            activation_text,
            parse_mode="HTML",
        )
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"Premium oluvchiga faollashgani haqida xabar yuborishda xatolik: {error}")
    if recipient_id != user_id:
        try:
            await bot.send_message(
                user_id,
                f"🎁 Sovg'angiz qabul qiluvchiga yuborildi. Premium muddati: "
                f"<b>{expires_at.strftime('%d.%m.%Y %H:%M')}</b>.",
                parse_mode="HTML",
            )
        except (TelegramBadRequest, TelegramForbiddenError) as error:
            print(f"Premium sovg'asi haqida to'lovchiga xabar yuborishda xatolik: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("✅ Premium obuna faollashtirildi.")


@dp.callback_query(F.data.startswith("premiumreject:"))
async def reject_premium_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID or not call.data:
        await call.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    payment_id = call.data.split(":", 1)[1]
    payment = PENDING_PREMIUM_PAYMENTS.pop(payment_id, None)
    if not payment:
        await call.answer("Chek topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    save_data()
    try:
        user_id = int(payment["user_id"])
        gift_recipient_id = payment.get("gift_recipient_id")
        await bot.send_message(
            user_id,
            (
                "⚠️ Premium sovg'a to'lov chekingiz tasdiqlanmadi. Admin bilan bog'laning."
                if gift_recipient_id is not None
                else "⚠️ Premium to'lov chekingiz tasdiqlanmadi. Batafsil ma'lumot uchun admin bilan bog'laning."
            ),
        )
    except (KeyError, TypeError, ValueError, TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"Premium chek rad etilgani haqida xabar yuborilmadi: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("Chek rad etildi.")


@dp.message(PremiumPaymentState.waiting_receipt, F.text)
async def premium_receipt_text_received(message: Message):
    await message.answer("📎 Iltimos, to'lov chekini rasm yoki fayl ko'rinishida yuboring.")


@dp.callback_query(F.data == "library_subscribe")
async def start_library_subscription(call: CallbackQuery, state: FSMContext):
    if has_library_access(call.from_user.id):
        await call.answer("✅ Kutubxonadan foydalanish huquqingiz bor.")
        return
    if not CARD_NUMBER or ADMIN_ID == 0:
        await call.answer("⚠️ To'lov ma'lumotlari sozlanmagan.", show_alert=True)
        return
    await state.clear()
    await state.set_state(LibraryPaymentState.waiting_receipt)
    await call.answer("💳 To'lov ma'lumotlari yuborildi.")
    message = get_callback_message(call)
    if message:
        card_name = CARD_NAME or "Ko'rsatilmagan"
        await message.answer(
            "📚 <b>Shaxsiy kino kutubxonasi — 30 kun</b>\n\n"
            f"💰 To'lov: <b>{LIBRARY_PRICE}</b>\n"
            f"💳 Karta: <code>{escape(CARD_NUMBER)}</code>\n"
            f"👤 Karta egasi: {escape(card_name)}\n\n"
            "To'lovdan so'ng chek rasmini yoki faylini shu chatga yuboring. "
            f"Chek admin @{escape(ADMIN_USERNAME or 'admin')} ga tasdiqlash uchun yuboriladi.",
            parse_mode="HTML",
        )


@dp.message(LibraryPaymentState.waiting_receipt, F.photo)
@dp.message(LibraryPaymentState.waiting_receipt, F.document)
async def library_receipt_received(message: Message, state: FSMContext):
    if message.from_user is None or ADMIN_ID == 0:
        return
    if message.from_user.id == ADMIN_ID:
        await state.clear()
        await message.answer("✅ Siz adminsiz. Kutubxona to'lov cheki kerak emas.")
        return
    user = message.from_user
    payment_id = uuid4().hex[:12]
    PENDING_LIBRARY_PAYMENTS[payment_id] = {"user_id": user.id}
    save_data()
    review_keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"libraryapprove:{payment_id}"),
        InlineKeyboardButton(text="❌ Rad etish", callback_data=f"libraryreject:{payment_id}"),
    ]])
    admin_caption = (
        "📚 <b>Shaxsiy kutubxona obunasi</b>\n\n"
        f"💰 To'lov: <b>{LIBRARY_PRICE}</b>\n"
        f"👤 Foydalanuvchi: <b>{escape(user.full_name)}</b>\n"
        f"🔗 Username: @{escape(user.username or '—')}\n"
        f"🆔 ID: <code>{user.id}</code>"
    )
    try:
        if message.photo:
            await bot.send_photo(
                ADMIN_ID,
                photo=message.photo[-1].file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=review_keyboard,
            )
        elif message.document:
            await bot.send_document(
                ADMIN_ID,
                document=message.document.file_id,
                caption=admin_caption,
                parse_mode="HTML",
                reply_markup=review_keyboard,
            )
        else:
            PENDING_LIBRARY_PAYMENTS.pop(payment_id, None)
            save_data()
            await message.answer("⚠️ Chekni rasm yoki fayl ko'rinishida yuboring.")
            return
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        PENDING_LIBRARY_PAYMENTS.pop(payment_id, None)
        save_data()
        print(f"Kutubxona to'lov chekini adminga yuborishda xatolik: {error}")
        await message.answer("⚠️ Chekni adminga yuborib bo'lmadi. Keyinroq qayta urinib ko'ring.")
        return
    await state.clear()
    await message.answer("✅ Chekingiz adminga yuborildi. Kutubxona obunasi tasdiqlangach faollashadi.")


@dp.message(LibraryPaymentState.waiting_receipt, F.text)
async def library_receipt_text_received(message: Message):
    await message.answer("📎 Iltimos, to'lov chekini rasm yoki fayl ko'rinishida yuboring.")


@dp.callback_query(F.data.startswith("libraryapprove:"))
async def approve_library_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID or not call.data:
        await call.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    payment_id = call.data.split(":", 1)[1]
    payment = PENDING_LIBRARY_PAYMENTS.pop(payment_id, None)
    if not payment:
        await call.answer("Chek topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    try:
        user_id = int(payment["user_id"])
    except (KeyError, TypeError, ValueError):
        save_data()
        await call.answer("Chek ma'lumotlari noto'g'ri.", show_alert=True)
        return
    expires_at = grant_library_subscription(user_id)
    save_data()
    try:
        await bot.send_message(
            user_id,
            "✅ To'lov tasdiqlandi! Shaxsiy kino kutubxonangiz 30 kunga faollashtirildi.\n"
            f"⏳ Amal qilish muddati: <b>{expires_at.strftime('%d.%m.%Y %H:%M')}</b>",
            parse_mode="HTML",
            reply_markup=library_menu_keyboard(),
        )
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"Kutubxona obunasi faollashganini foydalanuvchiga bildirishda xatolik: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("✅ Kutubxona obunasi faollashtirildi.")


@dp.callback_query(F.data.startswith("libraryreject:"))
async def reject_library_payment(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID or not call.data:
        await call.answer("❌ Ruxsat yo'q.", show_alert=True)
        return
    payment_id = call.data.split(":", 1)[1]
    payment = PENDING_LIBRARY_PAYMENTS.pop(payment_id, None)
    if not payment:
        await call.answer("Chek topilmadi yoki allaqachon ko'rib chiqilgan.", show_alert=True)
        return
    save_data()
    try:
        await bot.send_message(
            int(payment["user_id"]),
            "⚠️ Kutubxona obunasi uchun yuborgan chekingiz tasdiqlanmadi. Admin bilan bog'laning.",
        )
    except (KeyError, TypeError, ValueError, TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"To'lov rad etilgani haqida xabar yuborilmadi: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("Chek rad etildi.")


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
            f"├ Taklif qilganlar: {len(REFERRALS.get(user_id, set()))} ta\n"
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
        f"💎 Premium foydalanuvchilar: <b>{len(active_premium_user_ids())}</b>\n"
        f"🎬 Kinolar: <b>{len(MOVIES_DATABASE)}</b> ta\n"
        f"👁 Ko'rishlar: <b>{total_views}</b>\n"
        f"👍 Like'lar: <b>{total_likes}</b>\n"
        "🎁 Kunlik bepul limit: <b>Cheksiz</b>",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


@dp.message(F.text == "💎 Premium users")
async def premium_users_msg(message: Message):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    premium_users = sorted(active_premium_user_ids())
    if not premium_users:
        await message.answer(
            "💎 Hozircha Premium foydalanuvchilar yo'q.",
            reply_markup=build_admin_reply_keyboard(),
        )
        return
    lines = [f"💎 <b>Premium foydalanuvchilar ({len(premium_users)} ta):</b>\n"]
    users_updated = False
    for index, user_id in enumerate(premium_users, 1):
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
        expiry_text = ""
        if user_id in PREMIUM_SUBSCRIPTIONS:
            try:
                expiry_text = (
                    "├ Tugash vaqti: "
                    f"{datetime.fromisoformat(PREMIUM_SUBSCRIPTIONS[user_id]).strftime('%d.%m.%Y %H:%M')}\n"
                )
            except ValueError:
                pass
        lines.append(
            f"{index}. <b>{name}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {username}\n"
            f"{expiry_text}"
            f"└ Telefon: {phone}\n"
        )
    if users_updated:
        save_data()
    await message.answer(
        "\n".join(lines)[:4000],
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
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
        if movie.get("is_premiere"):
            badges.append("🎬")
        lines.append(f"<code>{code}</code> — {escape(str(movie.get('name', 'Nomsiz')))} {' '.join(badges)}")
    return "\n".join(lines)[:4000]


def build_movie_catalog_list() -> str:
    lines = [f"📚 <b>Barcha kinolar ({len(MOVIES_DATABASE)} ta)</b>\n"]
    for code in sorted(MOVIES_DATABASE, key=movie_code_sort_key):
        movie = MOVIES_DATABASE[code]
        lines.append(f"🎬 <b>{escape(str(movie.get('name', 'Nomsiz')))}</b> — kodi: <code>{code}</code>")
    lines.append("\n👇 Kino ko'rish uchun uning kodini chatga yuboring.")
    return "\n".join(lines)[:4000]


async def start_movie_add(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(AddMovie.file_id)
    await message.answer(
        "➕ <b>Yangi kino qo'shish</b>\n\n"
        "Qo'shmoqchi bo'lgan kinongizning videosini hozir shu chatga yuboring "
        "(video yoki fayl ko'rinishida).\n"
        "Video kelgach, kino nomi va qolgan ma'lumotlarini birma-bir so'rayman.\n"
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
    await message.answer("1/7 🎬 Kino nomini yuboring:")


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
    await save_add_movie_field(message, state, "name", AddMovie.til, "2/7 🗣 Tilini yuboring (masalan: O'zbek tilida):")


@dp.message(AddMovie.til, F.text)
async def movie_add_til(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "til", AddMovie.sifat, "3/7 📼 Sifatini yuboring (masalan: 1080p):")


@dp.message(AddMovie.sifat, F.text)
async def movie_add_sifat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "sifat", AddMovie.yil, "4/7 📅 Chiqqan yilini yuboring:")


@dp.message(AddMovie.yil, F.text)
async def movie_add_yil(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "yil", AddMovie.janr, "5/7 🎭 Janrini yuboring:")


@dp.message(AddMovie.janr, F.text)
async def movie_add_janr(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "janr", AddMovie.davlat, "6/7 🌍 Davlatini yuboring:")


@dp.message(AddMovie.davlat, F.text)
async def movie_add_davlat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "davlat", AddMovie.davomiyligi, "7/7 ⏳ Davomiyligini yuboring:")


@dp.message(AddMovie.davomiyligi, F.text)
async def movie_add_duration(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("⚠️ Davomiylikni matn ko'rinishida yuboring.")
        return
    await state.update_data(davomiyligi=message.text.strip())
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
        "is_premiere": False,
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
        await message.edit_text("ℹ️ Hozircha foydalanuvchilar bazasi bo'sh.", reply_markup=None)
        await message.answer("👑 Admin panel:", reply_markup=build_admin_reply_keyboard())
        return

    text = f"👥 <b>Foydalanuvchilar Bazasi (Jami: {len(ALL_USERS)} ta):</b>\n\n"

    for idx, user_id in enumerate(ALL_USERS, 1):
        info = USER_INFO.get(user_id, {})
        name = escape(str(info.get("name", "Noma'lum")))
        username = escape(str(info.get("username", "Mavjud emas")))
        phone = escape(str(info.get("phone", "Mavjud emas")))
        joined = escape(str(info.get("joined", "Noma'lum")))
        is_premium = "💎 Premium" if has_premium_access(user_id) else "🆓 Bepul"

        text += (
            f"<b>{idx}. {name}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {username}\n"
            f"├ Telefon: {phone}\n"
            f"├ Obuna: {is_premium}\n"
            f"├ Taklif qilganlar: <b>{len(REFERRALS.get(user_id, set()))}</b> ta\n"
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
        f"💎 Premium foydalanuvchilar: <b>{len(active_premium_user_ids())}</b>\n"
        f"🤝 Jami referal takliflar: <b>{sum(len(users) for users in REFERRALS.values())}</b>\n"
        f"🎬 Kinolar bazasi: <b>{len(MOVIES_DATABASE)}</b> ta\n"
        f"👁 Jami ko'rishlar: <b>{total_views}</b>\n"
        f"👍 Jami like'lar: <b>{total_likes}</b>\n"
        "🎁 Kunlik bepul limit: <b>Cheksiz</b>\n"
        f"🎬 Joriy premyera: <b>{MOVIES_DATABASE[CURRENT_PREMIERE]['name'] if CURRENT_PREMIERE and CURRENT_PREMIERE in MOVIES_DATABASE else 'Yo\u02bbq'}</b>\n"
        f"⏱ Bot ishlash vaqti: <b>{str(uptime).split('.')[0]}</b>"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]])
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)


@dp.callback_query(F.data == "admin_referrals")
async def show_referral_report(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return

    ranked_users = sorted(
        ALL_USERS,
        key=lambda user_id: (-len(REFERRALS.get(user_id, set())), user_id),
    )
    total_referrals = sum(len(REFERRALS.get(user_id, set())) for user_id in ALL_USERS)
    lines = [
        "👥 <b>Referallar hisoboti</b>\n",
        f"Jami taklif orqali kelganlar: <b>{total_referrals}</b>\n",
    ]
    for index, user_id in enumerate(ranked_users, 1):
        info = USER_INFO.get(user_id, {})
        name = escape(str(info.get("name", "Noma'lum")))
        username = escape(str(info.get("username", "Mavjud emas")))
        count = len(REFERRALS.get(user_id, set()))
        line = f"{index}. <b>{name}</b> — {count} ta | <code>{user_id}</code> ({username})\n"
        if sum(map(len, lines)) + len(line) > 3700:
            lines.append(f"\n⚠️ Ro'yxat uzun, jami foydalanuvchilar: {len(ranked_users)} ta.")
            break
        lines.append(line)

    await call.answer()
    await message.edit_text(
        "".join(lines),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]
        ]),
    )


@dp.callback_query(F.data == "admin_vip_manage")
async def admin_vip_manage_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.clear()
    await state.set_state(AdminVip.user_id)
    await call.answer()
    message = get_callback_message(call)
    if message:
        active_vips = sum(
            1 for user_id in LIBRARY_SUBSCRIPTIONS
            if has_library_access(user_id) and not has_premium_access(user_id)
        )
        await message.answer(
            f"💎 <b>VIP boshqarish</b>\nFaol VIP obunalar: <b>{active_vips}</b>\n\n"
            "VIP berish yoki muddatini uzaytirish uchun foydalanuvchi ID sini yuboring.\n"
            "Faol VIP obunasi bor ID yuborilsa, obuna bekor qilinadi. Bekor qilish: /cancel",
            parse_mode="HTML",
        )


@dp.message(AdminVip.user_id, F.text)
async def admin_vip_manage_finish(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    raw_user_id = message.text.strip()
    if not raw_user_id.isdigit() or int(raw_user_id) <= 0:
        await message.answer("⚠️ Foydalanuvchi ID sini musbat raqam sifatida yuboring.")
        return
    user_id = int(raw_user_id)
    if has_premium_access(user_id):
        await message.answer("ℹ️ Bu foydalanuvchi Premium orqali VIP kutubxonaga allaqachon kira oladi.")
        await state.clear()
        return
    if has_library_access(user_id):
        LIBRARY_SUBSCRIPTIONS.pop(user_id, None)
        save_data()
        await message.answer(f"✅ <code>{user_id}</code> foydalanuvchining VIP obunasi bekor qilindi.")
    else:
        expires_at = grant_library_subscription(user_id)
        save_data()
        await message.answer(
            f"✅ <code>{user_id}</code> foydalanuvchiga VIP 30 kunga berildi.\n"
            f"⏳ Tugash vaqti: <b>{expires_at.strftime('%d.%m.%Y %H:%M')}</b>",
            parse_mode="HTML",
        )
    await state.clear()


@dp.callback_query(F.data == "admin_payments")
async def show_pending_payments(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    premium_count = len(PENDING_PREMIUM_PAYMENTS)
    library_count = len(PENDING_LIBRARY_PAYMENTS)
    lines = [
        "💰 <b>Kutilayotgan to'lovlar</b>\n\n",
        f"⭐ Premium chek(lar): <b>{premium_count}</b>\n",
        f"💎 VIP kutubxona chek(lar): <b>{library_count}</b>\n\n",
        "Chekni tasdiqlash yoki rad etish uchun admin chatiga kelgan chek xabaridagi tugmalardan foydalaning.",
    ]
    if premium_count or library_count:
        lines.extend(["\n\n<b>Premium chek ID lari:</b>\n"])
        lines.extend(
            f"• <code>{escape(payment_id)}</code>\n"
            for payment_id in list(PENDING_PREMIUM_PAYMENTS)[:20]
        )
        lines.extend(["\n<b>VIP chek ID lari:</b>\n"])
        lines.extend(
            f"• <code>{escape(payment_id)}</code>\n"
            for payment_id in list(PENDING_LIBRARY_PAYMENTS)[:20]
        )
    message = get_callback_message(call)
    await call.answer()
    if message:
        await message.edit_text(
            "".join(lines),
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]
            ]),
        )


@dp.callback_query(F.data == "admin_requests")
async def show_movie_request_info(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            "📥 <b>Kino buyurtmalari</b>\n\n"
            "Yangi buyurtmalar admin chatiga foydalanuvchi nomi va so'ralgan kino bilan yuboriladi. "
            "Bot hozircha buyurtmalarni alohida navbatda saqlamaydi.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]
            ]),
        )


@dp.callback_query(F.data == "admin_promos")
async def show_promo_codes_info(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            "🎁 <b>Promo-kodlar</b>\n\nHozircha promo-kod tizimi sozlanmagan.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]
            ]),
        )


@dp.callback_query(F.data == "admin_settings")
async def show_admin_settings(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(
            "⚙️ <b>Sozlamalar</b>\n\n"
            f"🎬 Kinolar: <b>{len(MOVIES_DATABASE)}</b>\n"
            f"👥 Foydalanuvchilar: <b>{len(ALL_USERS)}</b>\n"
            f"🎞 Premyera kodi: <code>{escape(str(CURRENT_PREMIERE or 'yo‘q'))}</code>\n"
            "To'lov kartasi va admin ma'lumotlari .env faylidan boshqariladi.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💾 Ma'lumotlarni saqlash", callback_data="admin_save")],
                [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")],
            ]),
        )


@dp.callback_query(F.data == "admin_premium")
async def show_premium_users_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    premium_users = sorted(active_premium_user_ids())
    if not premium_users:
        text = "💎 <b>Premium users</b>\n\nHozircha Premium foydalanuvchilar yo'q."
    else:
        lines = [f"💎 <b>Premium users ({len(premium_users)} ta)</b>\n"]
        for index, user_id in enumerate(premium_users, 1):
            info = USER_INFO.get(user_id, {})
            name = escape(str(info.get("name", "Noma'lum")))
            username = escape(str(info.get("username", "Mavjud emas")))
            expiry = PREMIUM_SUBSCRIPTIONS.get(user_id)
            expiry_text = ""
            if expiry:
                try:
                    expiry_text = f" — {datetime.fromisoformat(expiry).strftime('%d.%m.%Y %H:%M')} gacha"
                except ValueError:
                    pass
            lines.append(
                f"{index}. <b>{name}</b> — <code>{user_id}</code> ({username}){expiry_text}"
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
        [InlineKeyboardButton(text="⏳ Davomiyligi", callback_data=f"editfield:{code}:davomiyligi")],
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
    state_data = await state.get_data()
    premium_action = state_data.get("premium_action", "toggle")
    if user_id == ADMIN_ID:
        await state.clear()
        await message.answer(
            "ℹ️ Admin akkauntining Premium huquqini bu yerdan olib bo'lmaydi.",
            reply_markup=build_admin_reply_keyboard(),
        )
        return
    currently_premium = has_premium_access(user_id)
    if premium_action == "grant" and currently_premium:
        result = "allaqachon faol"
    elif premium_action == "revoke" and not currently_premium:
        result = "allaqachon faol emas"
    elif premium_action == "grant":
        PREMIUM_OVERRIDES[user_id] = True
        result = "berildi"
        save_data()
    elif premium_action == "revoke":
        PREMIUM_OVERRIDES[user_id] = False
        PREMIUM_SUBSCRIPTIONS.pop(user_id, None)
        result = "olib tashlandi"
        save_data()
    elif currently_premium:
        PREMIUM_OVERRIDES[user_id] = False
        PREMIUM_SUBSCRIPTIONS.pop(user_id, None)
        result = "olib tashlandi"
        save_data()
    else:
        PREMIUM_OVERRIDES[user_id] = True
        result = "berildi"
        save_data()
    await state.clear()
    status = "💎 Premium faol" if has_premium_access(user_id) else "🆓 Premium bekor qilindi"
    await message.answer(
        f"✅ <code>{user_id}</code> foydalanuvchiga Premium {result}.\n{status}",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )


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
        "👑 <b>ADMIN PANEL</b>\nKerakli amalni pastki paneldan tanlang:",
        parse_mode="HTML",
        reply_markup=None,
    )
    await message.answer("👑 Admin panel:", reply_markup=build_admin_reply_keyboard())


def get_next_movie_code() -> str:
    """Eng katta raqamli kino kodidan keyingi kodni qaytaradi."""
    numeric_codes = [int(code) for code in MOVIES_DATABASE if str(code).isdigit()]
    return str(max(numeric_codes, default=0) + 1)


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
    if user_id is not None and not has_instagram_access(user_id):
        await target.answer(
            instagram_subscription_text(),
            parse_mode="HTML",
            reply_markup=instagram_subscription_keyboard(),
        )
        return
    if (
        user_id is not None
        and user_id != ADMIN_ID
        and not has_premium_access(user_id)
        and DAILY_FREE_LIMIT > 0
        and get_remaining_free_views(user_id) <= 0
    ):
        await target.answer(
            f"🎬 Bugungi bepul kino limitingiz ({DAILY_FREE_LIMIT} ta) tugadi.\n"
            "Cheksiz tomosha qilish uchun Premium tarifini tanlang:",
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
            if has_library_access(user_id):
                history = LIBRARY_HISTORY.setdefault(user_id, [])
                history.append({
                    "code": code,
                    "watched_at": datetime.now().isoformat(timespec="minutes"),
                })
                del history[:-50]
            save_data()
    except TelegramBadRequest:
        await target.answer("⚠️ Kinoni yuborishda xatolik yuz berdi. Telegram fayl ID eskirgan bo'lishi mumkin.")


# ======================================================================================
#  BOSH MENYU TUGMALARI: TASODIFIY, KUNNING KINOSI, TOP, SEVIMLILAR, STATISTIKA
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


@dp.message(F.text == "📚 Kino ro'yxati")
async def movie_catalog_msg(message: Message):
    register_user(message.from_user)
    if not MOVIES_DATABASE:
        await message.answer("❌ Hozircha bazada kinolar mavjud emas.")
        return
    await message.answer(build_movie_catalog_list(), parse_mode="HTML")


@dp.callback_query(F.data == "menu_movies")
async def movie_catalog_callback(call: CallbackQuery):
    register_user(call.from_user)
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    if not MOVIES_DATABASE:
        await message.answer("❌ Hozircha bazada kinolar mavjud emas.")
        return
    await message.answer(build_movie_catalog_list(), parse_mode="HTML")


@dp.message(F.text == "📅 Kunning kinosi")
async def daily_movie_msg(message: Message):
    if not MOVIES_DATABASE:
        await message.answer("❌ Hozircha bazada kinolar mavjud emas.")
        return
    register_user(message.from_user)
    codes = sorted(MOVIES_DATABASE.keys(), key=movie_code_sort_key)
    code = codes[date.today().toordinal() % len(codes)]
    await send_movie(message, code, MOVIES_DATABASE[code], message.from_user.id if message.from_user else None)


def latest_movies(limit: int = 10) -> list[tuple[str, dict]]:
    def year_key(item: tuple[str, dict]) -> tuple[int, tuple[int, int | str]]:
        code, movie = item
        match = re.search(r"\d{4}", str(movie.get("yil", "")))
        return (int(match.group()) if match else 0, movie_code_sort_key(code))

    return sorted(MOVIES_DATABASE.items(), key=year_key, reverse=True)[:limit]


async def send_latest_movies(message: Message) -> None:
    movies = latest_movies()
    if not movies:
        await message.answer("❌ Hozircha bazada kinolar mavjud emas.")
        return
    lines = ["🔥 <b>Yangi kinolar (chiqqan yiliga ko'ra):</b>\n"]
    for index, (code, movie) in enumerate(movies, 1):
        title = escape(str(movie.get("name", "Nomsiz")))
        year = escape(str(movie.get("yil", "Noma'lum")))
        lines.append(
            f"{index}. <b>{title}</b> — {year} | "
            f"kodi: <code>{escape(str(code))}</code>"
        )
    lines.append("\n👇 <i>Kinoni ko'rish uchun kodini yuboring!</i>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@dp.message(F.text == "🔥 Yangi kinolar")
async def latest_movies_msg(message: Message):
    await send_latest_movies(message)


@dp.callback_query(F.data == "menu_new")
async def latest_movies_callback(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message:
        await send_latest_movies(message)


@dp.message(F.text == "🔎 Kino qidirish")
async def movie_search_start(message: Message, state: FSMContext):
    await state.set_state(MovieSearchState.waiting)
    await message.answer("🔎 Kino nomi, janri yoki yilini yozib qidiring:")


@dp.callback_query(F.data == "menu_search")
async def movie_search_callback(call: CallbackQuery, state: FSMContext):
    await state.set_state(MovieSearchState.waiting)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("🔎 Kino nomi, janri yoki yilini yozib qidiring:")


@dp.message(MovieSearchState.waiting, F.text)
async def movie_search_finish(message: Message, state: FSMContext):
    if message.text is None:
        return
    matches = find_movie_matches(message.text)
    await state.clear()
    if not matches:
        await message.answer("🔎 Mos kino topilmadi. Boshqa nom, janr yoki yil bilan urinib ko'ring.")
        return
    await message.answer(
        build_results_text("🔎 <b>Qidiruv natijalari:</b>", matches),
        parse_mode="HTML",
    )


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
        text += f"{idx}. <b>{escape(str(movie['name']))}</b> — 👍 {len(movie['likes'])} | kodi: <code>{code}</code>\n"
    await message.answer(text, parse_mode="HTML")


@dp.message(F.text.in_({"⭐ Sevimlilarim", "❤️ Sevimlilar"}))
async def favorites_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    await send_library_section(message, user_id, "favorites")


@dp.message(F.text == "📜 Kino tarixi")
async def movie_history_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    await send_library_section(message, user_id, "history")


@dp.message(F.text == "📚 Shaxsiy kutubxona")
async def personal_library_msg(message: Message):
    if message.from_user is None:
        return
    await send_library_home(message, message.from_user.id)


@dp.message(F.text == "💎 VIP")
async def vip_membership_msg(message: Message):
    if message.from_user is None:
        return
    await send_library_home(message, message.from_user.id)


@dp.callback_query(F.data == "menu_library")
async def personal_library_callback(call: CallbackQuery):
    message = get_callback_message(call)
    await call.answer()
    if message:
        await send_library_home(message, call.from_user.id)


@dp.callback_query(F.data.startswith("library_view:"))
async def library_section_callback(call: CallbackQuery):
    if not call.data:
        await call.answer("⚠️ Bo'lim topilmadi.", show_alert=True)
        return
    section = call.data.split(":", 1)[1]
    message = get_callback_message(call)
    await call.answer()
    if message:
        await send_library_section(message, call.from_user.id, section)


@dp.callback_query(F.data.startswith("library_remove_later:"))
async def remove_from_watch_later(call: CallbackQuery):
    if not call.data:
        await call.answer("⚠️ Kino topilmadi.", show_alert=True)
        return
    if not has_library_access(call.from_user.id):
        await call.answer("🔒 Bu bo'lim uchun kutubxona obunasi kerak.", show_alert=True)
        message = get_callback_message(call)
        if message:
            await send_library_offer(message)
        return
    code = call.data.split(":", 1)[1]
    if code not in WATCH_LATER.get(call.from_user.id, set()):
        await call.answer("Bu kino ro'yxatda yo'q.")
        return
    WATCH_LATER[call.from_user.id].discard(code)
    save_data()
    await call.answer("🗑 Ro'yxatdan olib tashlandi.")
    message = get_callback_message(call)
    if message:
        codes = sorted(
            (item for item in WATCH_LATER.get(call.from_user.id, set()) if item in MOVIES_DATABASE),
            key=movie_code_sort_key,
        )
        matches = {item: MOVIES_DATABASE[item] for item in codes}
        if codes:
            await message.edit_text(
                build_results_text("🕒 <b>Keyinroq ko'rish ro'yxati:</b>", matches),
                parse_mode="HTML",
                reply_markup=library_later_keyboard(codes[:20]),
            )
        else:
            await message.edit_text(
                "🕒 Keyinroq ko'rish ro'yxatingiz bo'sh.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="◀️ Kutubxona", callback_data="menu_library")
                ]]),
            )


@dp.message(F.text.in_({"📊 Statistikam", "👤 Mening profilim"}))
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


@dp.message(F.text.in_({"📝 Kino so'rash", "📥 Kino buyurtma qilish"}))
async def request_movie_msg(message: Message, state: FSMContext):
    await state.set_state(MovieRequestState.waiting)
    await message.answer("📝 Qaysi kinoni topishni istaysiz? Nomini yozib yuboring.")


@dp.message(F.text.in_({"🤝 Do'stni taklif qilish", "🤝 Do'stlarni taklif qilish", "👥 Referal"}))
async def referral_msg(message: Message):
    user_id = message.from_user.id if message.from_user else 0
    link = f"https://t.me/{BOT_USERNAME}?start=ref{user_id}" if BOT_USERNAME else "Bot username aniqlanmagan"
    await message.answer(f"🤝 Shaxsiy taklif havolangiz:\n<code>{link}</code>", parse_mode="HTML")


@dp.message(F.text.in_({"📞 Admin bilan bog'lanish", "📞 Yordam"}))

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


@dp.callback_query(F.data == "menu_favorites")
async def show_favorites(call: CallbackQuery):
    message = get_callback_message(call)
    await call.answer()
    if message:
        await send_library_section(message, call.from_user.id, "favorites")


@dp.callback_query(F.data == "menu_stats")
async def show_my_stats(call: CallbackQuery):
    user_id = call.from_user.id
    register_user(call.from_user)
    info = USER_INFO.get(user_id, {})
    liked_count = sum(1 for m in MOVIES_DATABASE.values() if user_id in m["likes"])
    ref_count = len(REFERRALS.get(user_id, set()))
    is_premium = "💎 Ha" if has_premium_access(user_id) else "🆓 Yo'q"
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


@dp.callback_query(F.data == "menu_help")
async def show_help_contact(call: CallbackQuery):
    await call.answer()
    message = get_callback_message(call)
    if message is None:
        return
    if ADMIN_USERNAME:
        await message.answer(f"📞 Yordam uchun admin bilan bog'laning: https://t.me/{ADMIN_USERNAME}")
    else:
        await message.answer("⚠️ Yordam uchun admin username'i hali sozlanmagan.")


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


@dp.callback_query(F.data == "menu_home")
async def home_callback(call: CallbackQuery):
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await call.answer()
    await message.edit_text(
        f"👋 Salom, <b>{escape(call.from_user.full_name)}</b>!\n"
        "Gold Cinema botiga xush kelibsiz. Menyuni pastki paneldan tanlang.",
        parse_mode="HTML",
        reply_markup=None,
    )
    await message.answer(
        "🎬 Foydalanuvchi paneli:",
        reply_markup=build_user_reply_keyboard(),
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
    if not has_library_access(user_id):
        await call.answer("🔒 Sevimlilar uchun pullik kutubxona kerak.", show_alert=True)
        message = get_callback_message(call)
        if message:
            await send_library_offer(message)
        return
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


@dp.callback_query(F.data.startswith("later:"))
async def toggle_watch_later(call: CallbackQuery):
    if not call.data:
        await call.answer("❌ Noto'g'ri tugma.", show_alert=True)
        return
    code = call.data.split(":", 1)[1]
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        await call.answer("❌ Kino topilmadi.", show_alert=True)
        return
    user_id = call.from_user.id
    if not has_library_access(user_id):
        await call.answer("🔒 Keyinroq ro'yxati uchun pullik kutubxona kerak.", show_alert=True)
        message = get_callback_message(call)
        if message:
            await send_library_offer(message)
        return
    later = WATCH_LATER.setdefault(user_id, set())
    if code in later:
        later.discard(code)
        await call.answer("🗑 Keyinroq ro'yxatidan olib tashlandi.")
    else:
        later.add(code)
        await call.answer("🕒 Keyinroq ko'rish ro'yxatiga qo'shildi.")
    save_data()
    message = get_callback_message(call)
    if message:
        try:
            await message.edit_reply_markup(reply_markup=build_movie_keyboard(code, movie, user_id))
        except TelegramBadRequest:
            pass


@dp.message(StateFilter(None), F.text)
async def send_movie_by_code(message: Message):
    if message.text is None:
        return
    code = message.text.strip()
    movie = MOVIES_DATABASE.get(code)
    if movie is None:
        return
    register_user(message.from_user)
    user_id = message.from_user.id if message.from_user else None
    await send_movie(message, code, movie, user_id)


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