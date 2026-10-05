from aiogram import Router

import main as _main
from main import *

router = Router()

@router.message(F.text.in_({"👑 Admin panelni ochish", "👑 Admin panel"}))
async def admin_panel_msg(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer(
        "👑 <b>ADMIN PANEL</b>\nKerakli amalni pastki paneldan tanlang:",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )



@router.message(F.text == "⬇️ Tugmalarni yashirish")
async def refresh_legacy_admin_keyboard(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer(
        "✅ Admin panel yangilandi.",
        reply_markup=build_admin_reply_keyboard(),
    )



@router.callback_query(F.data == "admin_panel")
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



@router.message(
    F.text.in_({
        "📊 Statistika",
        "👥 Foydalanuvchilar",
        "💎 Premium obunachilar",
        "🆓 Oddiy obunachilar",
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
    elif action == "💎 Premium obunachilar":
        await admin_users_msg(message, premium_filter=True)
    elif action == "🆓 Oddiy obunachilar":
        await admin_users_msg(message, premium_filter=False)
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



@router.callback_query(F.data.startswith("admin_setting:"))
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
            "library_price": "🎬 Kino imkoniyatlarining 30 kunlik narxini so'mda yuboring (faqat raqam).",
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



@router.message(AdminSettings.value, F.text)
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



@router.callback_query(F.data.startswith("premiumapprove:"))
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
    ALL_USERS.add(recipient_id)
    USER_INFO.setdefault(
        recipient_id,
        {
            "name": "Noma'lum",
            "username": "Mavjud emas",
            "phone": "Mavjud emas",
            "joined": "Noma'lum",
        },
    )
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



@router.callback_query(F.data.startswith("premiumreject:"))
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



@router.callback_query(F.data.startswith("libraryapprove:"))
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
            "✅ To'lov tasdiqlandi! Kino imkoniyatlari obunasi 30 kunga faollashtirildi.\n"
            f"⏳ Amal qilish muddati: <b>{expires_at.strftime('%d.%m.%Y %H:%M')}</b>",
            parse_mode="HTML",
            reply_markup=library_menu_keyboard(),
        )
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"Kutubxona obunasi faollashganini foydalanuvchiga bildirishda xatolik: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("✅ Kino imkoniyatlari obunasi faollashtirildi.")



@router.callback_query(F.data.startswith("libraryreject:"))
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
            "⚠️ Kino imkoniyatlari obunasi uchun yuborgan chekingiz tasdiqlanmadi. Admin bilan bog'laning.",
        )
    except (KeyError, TypeError, ValueError, TelegramBadRequest, TelegramForbiddenError) as error:
        print(f"To'lov rad etilgani haqida xabar yuborilmadi: {error}")
    message = get_callback_message(call)
    if message:
        await message.edit_reply_markup(reply_markup=None)
    await call.answer("Chek rad etildi.")



@router.message(F.text == "👥 Foydalanuvchilar ro'yxati")
async def admin_users_msg(message: Message, premium_filter: bool | None = None):
    if message.from_user is None or message.from_user.id != ADMIN_ID:
        return
    premium_users = active_premium_user_ids()
    candidate_users = set(ALL_USERS) | premium_users | set(PREMIUM_OVERRIDES)
    if premium_filter is True:
        user_ids = {
            user_id for user_id in candidate_users
            if has_premium_access(user_id)
        }
        title = "💎 <b>Premium obunachilar</b>"
    elif premium_filter is False:
        user_ids = {
            user_id for user_id in ALL_USERS
            if not has_premium_access(user_id)
        }
        title = "🆓 <b>Oddiy obunachilar</b>"
    else:
        user_ids = set(ALL_USERS)
        title = "👥 <b>Foydalanuvchilar bazasi</b>"
    if not user_ids:
        empty_message = (
            "ℹ️ Bu ro'yxatda hozircha foydalanuvchi yo'q."
            if premium_filter is not None
            else "ℹ️ Hozircha foydalanuvchilar bazasi bo'sh."
        )
        await message.answer(
            empty_message,
            reply_markup=build_admin_reply_keyboard(),
        )
        return
    premium_count = sum(not has_premium_access(user_id) for user_id in user_ids)
    free_count = len(user_ids) - premium_count
    text = (
        f"{title} (jami: {len(user_ids)} ta)\n"
        f"💎 Premium: <b>{premium_count}</b> | 🆓 Bepul: <b>{free_count}</b>\n\n"
    )
    for idx, user_id in enumerate(sorted(user_ids), 1):
        info = USER_INFO.get(user_id, {})
        name = info.get("name", "Noma'lum")
        joined = info.get("joined", "Noma'lum")
        phone = info.get("phone", "Mavjud emas")
        premium_status = (
            "🆓 Bepul" if has_premium_access(user_id) else "💎 Premium"
        )
        text += (
            f"<b>{idx}. {escape(str(name))}</b>\n"
            f"├ ID: <code>{user_id}</code>\n"
            f"├ Username: {escape(str(info.get('username', 'Mavjud emas')))}\n"
            f"├ Telefon: {escape(str(phone))}\n"
            f"├ Obuna: {premium_status}\n"
            f"├ Taklif qilganlar: <b>{len(REFERRALS.get(user_id, set()))}</b> ta\n"
            f"└ Qo'shilgan: {escape(str(joined))}\n\n"
        )
    await message.answer(text[:4000], parse_mode="HTML", reply_markup=build_admin_reply_keyboard())



@router.message(F.text == "📊 Bot statistikasi")
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



@router.message(F.text == "💎 Premium users")
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



@router.message(F.text == "💾 Ma'lumotlarni saqlash")
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



@router.message(F.text == "/cancel")
async def cancel_admin_action(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.clear()
        await message.answer("✅ Amal bekor qilindi.", reply_markup=build_admin_reply_keyboard())



@router.callback_query(F.data == "admin_add")
async def admin_add_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await start_movie_add(message, state)



@router.message(AddMovie.file_id, F.video)
@router.message(AddMovie.file_id, F.document)
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
    await message.answer(
        f"🔑 <b>File ID:</b> <code>{file_id}</code>\n\n"
        "1/7 🎬 Kino nomini yuboring:",
        parse_mode="HTML",
    )



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



@router.message(AddMovie.name, F.text)
async def movie_add_name(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "name", AddMovie.til, "2/7 🗣 Tilini yuboring (masalan: O'zbek tilida):")



@router.message(AddMovie.til, F.text)
async def movie_add_til(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "til", AddMovie.sifat, "3/7 📼 Sifatini yuboring (masalan: 1080p):")



@router.message(AddMovie.sifat, F.text)
async def movie_add_sifat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "sifat", AddMovie.yil, "4/7 📅 Chiqqan yilini yuboring:")



@router.message(AddMovie.yil, F.text)
async def movie_add_yil(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "yil", AddMovie.janr, "5/7 🎭 Janrini yuboring:")



@router.message(AddMovie.janr, F.text)
async def movie_add_janr(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "janr", AddMovie.davlat, "6/7 🌍 Davlatini yuboring:")



@router.message(AddMovie.davlat, F.text)
async def movie_add_davlat(message: Message, state: FSMContext):
    await save_add_movie_field(message, state, "davlat", AddMovie.davomiyligi, "7/7 ⏳ Davomiyligini yuboring:")



@router.message(AddMovie.davomiyligi, F.text)
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



@router.message(F.text.in_({"➕ Kino qo'shish", "🗑 Kino o'chirish", "✏️ Kino tahrirlash", "🎬 Premyera sozlash", "👑 Premium berish/olish", "📚 Kino ro'yxati"}))
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



@router.message(DeleteMovie.code)
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

    if _main.CURRENT_PREMIERE == code:
        _main.CURRENT_PREMIERE = None
    save_data()
    await message.answer(
        f"✅ <b>{escape(str(movie['name']))}</b> o'chirildi.",
        parse_mode="HTML",
        reply_markup=build_admin_reply_keyboard(),
    )



@router.message(F.text == "📢 Xabar yuborish")
async def admin_broadcast_msg(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.set_state(BroadcastState.message)
        await message.answer("📢 Yuboriladigan xabar matnini kiriting:")



@router.message(F.text == "🗳 So'rovnoma yuborish")
async def admin_poll_msg(message: Message, state: FSMContext):
    if message.from_user and message.from_user.id == ADMIN_ID:
        await state.set_state(AdminPollState.waiting)
        await message.answer("🗳 Format: Savol | Variant 1 | Variant 2 | Variant 3")



@router.callback_query(F.data == "admin_users")
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



@router.callback_query(F.data == "admin_stats")
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
        f"🎬 Joriy premyera: <b>{MOVIES_DATABASE[_main.CURRENT_PREMIERE]['name'] if _main.CURRENT_PREMIERE and _main.CURRENT_PREMIERE in MOVIES_DATABASE else 'Yo\u02bbq'}</b>\n"
        f"⏱ Bot ishlash vaqti: <b>{str(uptime).split('.')[0]}</b>"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")]])
    message = get_callback_message(call)
    if message is None:
        await call.answer("⚠️ Bu xabarni o'zgartirib bo'lmaydi.", show_alert=True)
        return
    await message.edit_text(text, parse_mode="HTML", reply_markup=back_kb)



@router.callback_query(F.data == "admin_referrals")
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



@router.callback_query(F.data == "admin_vip_manage")
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



@router.message(AdminVip.user_id, F.text)
async def admin_vip_manage_finish(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    raw_user_id = message.text.strip()
    if not raw_user_id.isdigit() or int(raw_user_id) <= 0:
        await message.answer("⚠️ Foydalanuvchi ID sini musbat raqam sifatida yuboring.")
        return
    user_id = int(raw_user_id)
    if has_premium_access(user_id):
        await message.answer("ℹ️ Bu foydalanuvchi Premium orqali kino imkoniyatlaridan allaqachon foydalana oladi.")
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



@router.callback_query(F.data == "admin_payments")
async def show_pending_payments(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    premium_count = len(PENDING_PREMIUM_PAYMENTS)
    library_count = len(PENDING_LIBRARY_PAYMENTS)
    lines = [
        "💰 <b>Kutilayotgan to'lovlar</b>\n\n",
        f"⭐ Premium chek(lar): <b>{premium_count}</b>\n",
        f"🎬 Kino imkoniyatlari chek(lar): <b>{library_count}</b>\n\n",
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



@router.callback_query(F.data == "admin_requests")
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



@router.callback_query(F.data == "admin_promos")
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



@router.callback_query(F.data == "admin_settings")
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
            f"🎞 Premyera kodi: <code>{escape(str(_main.CURRENT_PREMIERE or 'yo‘q'))}</code>\n"
            "To'lov kartasi va admin ma'lumotlari .env faylidan boshqariladi.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💾 Ma'lumotlarni saqlash", callback_data="admin_save")],
                [InlineKeyboardButton(text="◀️ Admin panelga qaytish", callback_data="admin_panel_back")],
            ]),
        )



@router.callback_query(F.data == "admin_premium")
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



@router.callback_query(F.data == "admin_save")
async def save_from_admin_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    save_data()
    await call.answer("✅ Ma'lumotlar saqlandi!", show_alert=True)



@router.callback_query(F.data == "admin_export")
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



@router.callback_query(F.data == "admin_delete")
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



@router.callback_query(F.data == "admin_edit")
async def admin_edit_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(EditMovie.code)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("✏️ Tahrirlanadigan kino kodini yuboring:")



@router.message(EditMovie.code, F.text)
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



@router.callback_query(F.data.startswith("editfield:"))
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



@router.message(EditMovie.value, F.text)
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



@router.callback_query(F.data == "admin_movies")
async def admin_movies_panel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.edit_text(build_movie_admin_list(), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="◀️ Admin panel", callback_data="admin_panel")]]))



@router.callback_query(F.data == "admin_premium_manage")
async def admin_premium_manage_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AdminPremium.user_id)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("👑 Premium beriladigan yoki olinadigan foydalanuvchi ID sini yuboring:")



@router.message(AdminPremium.user_id, F.text)
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



@router.callback_query(F.data == "admin_premiere")
async def admin_premiere_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(AdminPremiere.code)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("🎬 Premyera qilinadigan kino kodini yuboring. 0 yuborsangiz premyera o'chadi:")



@router.message(AdminPremiere.code, F.text)
async def admin_premiere_finish(message: Message, state: FSMContext):

    if message.from_user is None or message.from_user.id != ADMIN_ID or not message.text:
        return
    code = message.text.strip()
    if code == "0":
        _main.CURRENT_PREMIERE = None
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
    _main.CURRENT_PREMIERE = code
    save_data()
    await state.clear()
    await message.answer(f"✅ <b>{escape(str(MOVIES_DATABASE[code]['name']))}</b> premyera qilindi.", parse_mode="HTML", reply_markup=build_admin_reply_keyboard())



@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_start(call: CallbackQuery, state: FSMContext):
    if call.from_user.id != ADMIN_ID:
        await call.answer("❌ Siz admin emassiz!", show_alert=True)
        return
    await state.set_state(BroadcastState.message)
    await call.answer()
    message = get_callback_message(call)
    if message:
        await message.answer("📢 Barcha foydalanuvchilarga yuboriladigan xabar matnini kiriting:")



@router.message(BroadcastState.message)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if message.from_user is None or message.from_user.id != ADMIN_ID or message.text is None:
        return
    await state.clear()
    ok, fail = await broadcast_text(message.text)
    await message.answer(f"✅ Xabar yuborildi!\nMuvaffaqiyatli: {ok} ta\nXato: {fail} ta")



@router.callback_query(F.data == "admin_poll")
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



@router.message(AdminPollState.waiting)
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



@router.callback_query(F.data == "admin_panel_back")
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



@router.message(F.video)
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



@router.message(F.document)
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
