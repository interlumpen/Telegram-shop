DEFAULT_LOCALE = "ru"

TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # === Common Buttons ===
        "btn.shop": "🏪 Магазин",
        "btn.rules": "📜 Правила",
        "btn.profile": "👤 Профиль",
        "btn.support": "🆘 Поддержка",
        "btn.channel": "ℹ Новостной канал",
        "btn.admin_menu": "🎛 Панель администратора",
        "btn.back": "⬅️ Назад",
        "btn.to_menu": "🏠 В меню",
        "btn.close": "✖ Закрыть",
        "btn.buy": "🛒 Купить",
        "btn.yes": "✅ Да",
        "btn.no": "❌ Нет",
        "btn.check": "🔄 Проверить",
        "btn.check_subscription": "🔄 Проверить подписку",
        "btn.pay": "💳 Оплатить",
        "btn.check_payment": "🔄 Проверить оплату",
        "btn.pay.crypto": "💎 CryptoPay",
        "btn.pay.stars": "⭐ Telegram Stars",
        "btn.pay.tg": "💸 Telegram Payments",

        # === Admin Buttons (user management shortcuts) ===
        "btn.admin.view_profile": "👁 Посмотреть профиль",
        "btn.admin.promote": "⬆️ Назначить администратором",
        "btn.admin.demote": "⬇️ Снять администратора",
        "btn.admin.replenish_user": "💸 Пополнить баланс",
        "btn.admin.deduct_user": "💳 Списать с баланса",
        "btn.admin.block": "🚫 Заблокировать",
        "btn.admin.unblock": "✅ Разблокировать",

        # === Titles / Generic Texts ===
        "menu.title": "⛩️ Основное меню",
        "profile.caption": "👤 <b>Профиль</b> — <a href='tg://user?id={id}'>{name}</a>",
        "rules.not_set": "❌ Правила не были добавлены",

        # === Subscription Flow ===
        "subscribe.prompt": "Для начала подпишитесь на новостной канал",
        "subscribe.open_channel": "Открыть канал",

        # === Profile ===
        "profile.referral_id": "👤 <b>Реферал</b> — <code>{id}</code>",
        "btn.replenish": "💳 Пополнить баланс",
        "btn.referral": "🎲 Реферальная система",
        "btn.purchased": "🎁 Купленные товары",

        # === Profile Info Lines ===
        "profile.id": "🆔 <b>ID</b> — <code>{id}</code>",
        "profile.balance": "💳 <b>Баланс</b> — <code>{amount}</code> {currency}",
        "profile.total_topup": "💵 <b>Всего пополнено</b> — <code>{amount}</code> {currency}",
        "profile.purchased_count": "🎁 <b>Куплено товаров</b> — {count} шт",
        "profile.registration_date": "🕢 <b>Дата регистрации</b> — <code>{dt}</code>",

        # === Referral ===
        "referral.title": "💚 Реферальная система",
        "referral.link": "🔗 Ссылка: https://t.me/{bot_username}?start={user_id}",
        "referral.count": "Количество рефералов: {count}",
        "referral.description": (
            "📔 Реферальная система позволит Вам заработать деньги без всяких вложений. "
            "Необходимо всего лишь распространять свою реферальную ссылку и Вы будете получать "
            "{percent}% от суммы пополнений Ваших рефералов на Ваш баланс бота."
        ),
        "btn.view_referrals": "👥 Мои рефералы",
        "btn.view_earnings": "💰 Мои поступления",
        "btn.back_to_referral": "⬅️ К реферальной системе",

        "referrals.list.title": "👥 Ваши рефералы:",
        "referrals.list.empty": "У вас пока нет активных рефералов",
        "referrals.item.format": "ID: {telegram_id} | Принёс: {total_earned} {currency}",

        "referral.earnings.title": "💰 Поступления от реферала <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>):",
        "referral.earnings.empty": "От данного реферала <code>{id}</code> (<a href='tg://user?id={id}'>{name}</a>) пока не было поступлений",
        "referral.earning.format": "{amount} {currency} | {date} | (с {original_amount} {currency})",
        "referral.item.info": ("💰 Поступление номер: <code>{id}</code>\n"
                               "👤 Реферал: <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>)\n"
                               "🔢 Количество: {amount} {currency}\n"
                               "🕘 Дата: <code>{date}</code>\n"
                               "💵 С пополнения на {original_amount} {currency}"),

        "all.earnings.title": "💰 Все ваши реферальные поступления:",
        "all.earnings.empty": "У вас пока нет реферальных поступлений",
        "all.earning.format": "{amount} {currency} от ID:{referral_id} | {date}",

        "referrals.stats.template": (
            "📊 Статистика реферальной системы:\n\n"
            "👥 Активных рефералов: {active_count}\n"
            "💰 Всего заработано: {total_earned} {currency}\n"
            "📈 Общая сумма пополнений рефералов: {total_original} {currency}\n"
            "🔢 Количество начислений: {earnings_count}"
        ),

        # === Admin: Main Menu ===
        "admin.menu.main": "⛩️ Меню администратора",
        "admin.menu.shop": "🛒 Управление магазином",
        "admin.menu.goods": "📦 Управление позициями",
        "admin.menu.categories": "📂 Управление категориями",
        "admin.menu.users": "👥 Управление пользователями",
        "admin.menu.broadcast": "📝 Рассылка",
        "admin.menu.roles": "🛡 Управление ролями",
        "admin.menu.rights": "Недостаточно прав",

        # === Admin: Role Management ===
        "admin.roles.list_title": "🛡 Роли системы:",
        "admin.roles.create": "➕ Создать роль",
        "admin.roles.edit": "✏️ Редактировать",
        "admin.roles.delete": "🗑 Удалить",
        "admin.roles.detail": "🛡 <b>Роль</b>: {name}\n📋 Права: {perms}\n👥 Пользователей: {users}",
        "admin.roles.prompt_name": "Введите название роли (макс. 64 символа):",
        "admin.roles.name_invalid": "⚠️ Некорректное название (пустое или длиннее 64 символов).",
        "admin.roles.name_exists": "❌ Роль с таким именем уже существует",
        "admin.roles.select_perms": "Выберите права для роли «{name}»:",
        "admin.roles.confirm": "✅ Подтвердить",
        "admin.roles.created": "✅ Роль «{name}» создана",
        "admin.roles.updated": "✅ Роль «{name}» обновлена",
        "admin.roles.deleted": "✅ Роль удалена",
        "admin.roles.delete_confirm": "Вы уверены, что хотите удалить роль «{name}»?",
        "admin.roles.delete_fail": "❌ Не удалось удалить: {error}",
        "admin.roles.perm_denied": "⚠️ Недостаточно прав для этого действия",
        "admin.roles.assign_prompt": "Выберите роль для пользователя {id}:",
        "admin.roles.assigned": "✅ Роль {role} назначена пользователю {name}",
        "admin.roles.assigned_notify": "ℹ️ Вам назначена роль: {role}",
        "admin.roles.edit_name_prompt": "Введите новое название роли (или /skip чтобы оставить текущее):",
        "btn.admin.assign_role": "🛡 Назначить роль",

        # === Admin: User Management ===
        "admin.users.prompt_enter_id": "👤 Введите id пользователя,\nчтобы посмотреть | изменить его данные",
        "admin.users.invalid_id": "⚠️ Введите корректный числовой ID пользователя.",
        "admin.users.profile_unavailable": "❌ Профиль недоступен (такого пользователя никогда не существовало)",
        "admin.users.not_found": "❌ Пользователь не найден",
        "admin.users.cannot_change_owner": "Нельзя менять роль владельца",
        "admin.users.referrals": "👥 <b>Рефералы пользователя</b> — {count}",
        "admin.users.btn.view_referrals": "👥 Рефералы пользователя",
        "admin.users.btn.view_earnings": "💰 Поступления",
        "admin.users.role": "🎛 <b>Роль</b> — {role}",
        "admin.users.set_admin.success": "✅ Роль присвоена пользователю {name}",
        "admin.users.set_admin.notify": "✅ Вам присвоена роль АДМИНИСТРАТОРА бота",
        "admin.users.remove_admin.success": "✅ Роль отозвана у пользователя {name}",
        "admin.users.remove_admin.notify": "❌ У вас отозвана роль АДМИНИСТРАТОРА бота",
        "admin.users.balance.topped": "✅ Баланс пользователя {name} пополнен на {amount} {currency}",
        "admin.users.balance.topped.notify": "✅ Ваш баланс пополнен на {amount} {currency}",
        "admin.users.balance.deducted": "✅ С баланса пользователя {name} списано {amount} {currency}",
        "admin.users.balance.deducted.notify": "ℹ️ С вашего баланса списано {amount} {currency}",
        "admin.users.balance.insufficient": "❌ Недостаточно средств. Текущий баланс: {balance} {currency}",
        "admin.users.blocked.success": "🚫 Пользователь {name} заблокирован",
        "admin.users.unblocked.success": "✅ Пользователь {name} разблокирован",
        "admin.users.cannot_block_owner": "❌ Невозможно заблокировать владельца",
        "admin.users.status.blocked": "🚫 <b>Статус</b> — Заблокирован",

        # === Admin: Shop Management Menu ===
        "admin.shop.menu.title": "⛩️ Меню управления магазином",
        "admin.shop.menu.statistics": "📊 Статистика",
        "admin.shop.menu.logs": "📁 Показать логи",
        "admin.shop.menu.admins": "👮 Администраторы",
        "admin.shop.menu.users": "👤 Пользователи",
        "admin.shop.menu.search_bought": "🔎 Поиск купленного товара",

        # === Admin: Categories Management ===
        "admin.categories.menu.title": "⛩️ Меню управления категориями",
        "admin.categories.add": "➕ Добавить категорию",
        "admin.categories.rename": "✏️ Переименовать категорию",
        "admin.categories.delete": "🗑 Удалить категорию",
        "admin.categories.prompt.add": "Введите название новой категории:",
        "admin.categories.prompt.delete": "Введите название категории для удаления:",
        "admin.categories.prompt.rename.old": "Введите текущее название категории, которую нужно переименовать:",
        "admin.categories.prompt.rename.new": "Введите новое имя для категории:",
        "admin.categories.add.exist": "❌ Категория не создана (такая уже существует)",
        "admin.categories.add.success": "✅ Категория создана",
        "admin.categories.delete.not_found": "❌ Категория не удалена (такой категории не существует)",
        "admin.categories.delete.success": "✅ Категория удалена",
        "admin.categories.rename.not_found": "❌ Категория не может быть обновлена (такой категории не существует)",
        "admin.categories.rename.exist": "❌ Переименование невозможно (категория с таким именем уже существует)",
        "admin.categories.rename.success": "✅ Категория \"{old}\" переименована в \"{new}\"",

        # === Admin: Goods / Items Management (Add / List / Item Info) ===
        "admin.goods.add_position": "➕ Добавить позицию",
        "admin.goods.add_item": "➕ Добавить товар в позицию",
        "admin.goods.update_position": "📝 Изменить позицию",
        "admin.goods.delete_position": "❌ Удалить позицию",
        "admin.goods.show_items": "📄 Показать товары в позиции",
        "admin.goods.add.prompt.name": "Введите название позиции",
        "admin.goods.add.name.exists": "❌ Позиция не может быть создана (такая позиция уже существует)",
        "admin.goods.add.prompt.description": "Введите описание для позиции:",
        "admin.goods.add.prompt.price": "Введите цену для позиции (число в {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Некорректное значение цены. Введите число.",
        "admin.goods.add.prompt.category": "Введите категорию, к которой будет относиться позиция:",
        "admin.goods.add.category.not_found": "❌ Позиция не может быть создана (категория для привязки введена неверно)",
        "admin.goods.add.infinity.question": "У этой позиции будут бесконечные товары? (всем будет высылаться одна копия значения)",
        "admin.goods.add.values.prompt_multi": (
            "Введите товары для позиции по одному сообщению.\n"
            "Когда закончите ввод — нажмите «Добавить указанные товары»."
        ),
        "admin.goods.add.values.added": "✅ Товар «{value}» добавлен в список ({count} шт.)",
        "admin.goods.add.result.created": "✅ Позиция создана.",
        "admin.goods.add.result.added": "📦 Добавлено товаров: <b>{n}</b>",
        "admin.goods.add.result.skipped_db_dup": "↩️ Пропущено (уже были в БД): <b>{n}</b>",
        "admin.goods.add.result.skipped_batch_dup": "🔁 Пропущено (дубль в вводе): <b>{n}</b>",
        "admin.goods.add.result.skipped_invalid": "🚫 Пропущено (пустые/некорректные): <b>{n}</b>",
        "admin.goods.add.single.prompt_value": "Введите одно значение товара для позиции:",
        "admin.goods.add.single.empty": "⚠️ Значение не может быть пустым.",
        "admin.goods.add.single.created": "✅ Позиция создана, значение добавлено",
        "btn.add_values_finish": "Добавить указанные товары",
        "admin.goods.position.not_found": "❌ Товаров нет (Такой позиции не существует)",
        "admin.goods.list_in_position.empty": "ℹ️ В этой позиции пока нет товаров.",
        "admin.goods.list_in_position.title": "Товары в позиции:",
        "admin.goods.item.invalid": "Некорректные данные",
        "admin.goods.item.invalid_id": "Некорректный ID товара",
        "admin.goods.item.not_found": "Товар не найден",
        "admin.goods.prompt.enter_item_name": "Введите название позиции",
        "admin.goods.menu.title": "⛩️ Меню управления позициями",

        # === Admin: Goods / Items Update Flow ===
        "admin.goods.update.amount.prompt.name": "Введите название позиции",
        "admin.goods.update.amount.not_exists": "❌ Товар не может быть добавлен (такой позиции не существует)",
        "admin.goods.update.amount.infinity_forbidden": "❌ Товар не может быть добавлен (у данной позиции бесконечный товар)",
        "admin.goods.update.values.result.title": "✅ Товары добавлены",
        "admin.goods.update.position.invalid": "Позиция не найдена.",
        "admin.goods.update.position.exists": "Позиция с таким именем уже существует.",
        "admin.goods.update.prompt.name": "Введите название позиции",
        "admin.goods.update.not_exists": "❌ Позиция не может быть изменена (такой позиции не существует)",
        "admin.goods.update.prompt.new_name": "Введите новое имя для позиции:",
        "admin.goods.update.prompt.description": "Введите описание для позиции:",
        "admin.goods.update.infinity.make.question": "Вы хотите сделать товары бесконечными?",
        "admin.goods.update.infinity.deny.question": "Вы хотите отменить бесконечные товары?",
        "admin.goods.update.success": "✅ Позиция обновлена",

        # === Admin: Goods / Items Delete Flow ===
        "admin.goods.delete.prompt.name": "Введите название позиции",
        "admin.goods.delete.position.not_found": "❌ Позиция не удалена (Такой позиции не существует)",
        "admin.goods.delete.position.success": "✅ Позиция удалена",
        "admin.goods.item.delete.button": "❌ Удалить товар",
        "admin.goods.item.already_deleted_or_missing": "Товар уже удалён или не найден",
        "admin.goods.item.deleted": "✅ Товар удалён",

        # === Admin: Item Info ===
        "admin.goods.item.info.position": "<b>Позиция</b>: <code>{name}</code>",
        "admin.goods.item.info.price": "<b>Цена</b>: <code>{price}</code> {currency}",
        "admin.goods.item.info.id": "<b>Уникальный ID</b>: <code>{id}</code>",
        "admin.goods.item.info.value": "<b>Товар</b>: <code>{value}</code>",

        # === Admin: Logs ===
        "admin.shop.logs.caption": "Логи бота",
        "admin.shop.logs.empty": "❗️ Логов пока нет",

        # === Group Notifications ===
        "shop.group.new_upload": "Залив",
        "shop.group.item": "Товар",
        "shop.group.count": "Количество",

        # === Admin: Statistics ===
        "admin.shop.stats.template": (
            "Статистика магазина:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<b>◽ПОЛЬЗОВАТЕЛИ</b>\n"
            "◾️Пользователей за 24 часа: {today_users}\n"
            "◾️Всего администраторов: {admins}\n"
            "◾️Всего пользователей: {users}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>СРЕДСТВА</b>\n"
            "◾Продаж за 24 часа на: {today_orders} {currency}\n"
            "◾Продано товаров на: {all_orders} {currency}\n"
            "◾Пополнений за 24 часа: {today_topups} {currency}\n"
            "◾Средств в системе: {system_balance} {currency}\n"
            "◾Пополнено: {all_topups} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>ПРОЧЕЕ</b>\n"
            "◾Товаров: {items} шт.\n"
            "◾Позиций: {goods} шт.\n"
            "◾Категорий: {categories} шт.\n"
            "◾Продано товаров: {sold_count} шт."
        ),

        # === Admin: Lists & Broadcast ===
        "admin.shop.admins.title": "👮 Администраторы бота:",
        "admin.shop.users.title": "Пользователи бота:",
        "admin.shop.bought.prompt_id": "Введите уникальный ID купленного товара",
        "admin.shop.bought.not_found": "❌ Товар с указанным уникальным ID не найден",
        "broadcast.prompt": "Отправьте сообщение для рассылки:",
        "broadcast.creating": "📤 Начинаем рассылку...\n👥 Всего пользователей: {ids}",
        "broadcast.progress": (
            "📤 Рассылка в процессе...\n\n"
            "📊 Прогресс: {progress:.1f}%\n"
            "✅ Отправлено: {sent}/{total}\n"
            "❌ Ошибок: {failed}\n"
            "⏱ Прошло времени: {time} сек"),
        "broadcast.done": (
            "✅ Рассылка завершена!\n\n"
            "📊 Статистика:\n"
            "👥 Всего: {total}\n"
            "✅ Доставлено: {sent}\n"
            "❌ Не доставлено: {failed}\n"
            "🚫 Заблокировали бота: ~{blocked}\n"
            "📈 Успешность: {success}%\n"
            "⏱ Время: {duration} сек"
        ),
        "broadcast.cancel": "❌ Рассылка отменена",
        "broadcast.warning": "Нет активной рассылки",

        # === Payments / Top-up Flow ===
        "payments.replenish_prompt": "Введите сумму пополнения в {currency}:",
        "payments.replenish_invalid": "❌ Неверная сумма. Введите число от {min_amount} до {max_amount} {currency}.",
        "payments.deduct_prompt": "Введите сумму списания в {currency}:",
        "payments.deduct_invalid": "❌ Неверная сумма. Введите число от {min_amount} до {max_amount} {currency}.",
        "payments.method_choose": "Выберите способ оплаты:",
        "payments.not_configured": "❌ Пополнение не настроено",
        "payments.session_expired": "Сессия оплаты устарела. Начните заново.",
        "payments.crypto.create_fail": "❌ Ошибка при создании счёта: {error}",
        "payments.crypto.api_error": "❌ Ошибка CryptoPay API: {error}",
        "payments.crypto.check_fail": "❌ Ошибка проверки платежа: {error}",
        "payments.stars.create_fail": "❌ Не удалось выставить счёт в Stars: {error}",
        "payments.fiat.create_fail": "❌ Не удалось выставить счёт: {error}",
        "payments.no_active_invoice": "❌ Активных счетов не найдено. Начните пополнение заново.",
        "payments.invoice_not_found": "❌ Счёт не найден. Начните заново.",
        "payments.not_paid_yet": "⌛️ Платёж ещё не оплачен.",
        "payments.expired": "❌ Срок действия счёта истёк.",
        "payments.invoice.summary": (
            "💵 Сумма пополнения: {amount} {currency}.\n"
            "⌛️ У вас есть {minutes} минут на оплату.\n"
            "<b>❗️ После оплаты нажмите кнопку «{button}»</b>"
        ),
        "payments.unable_determine_amount": "❌ Не удалось определить сумму оплаты.",
        "payments.topped_simple": "✅ Баланс пополнен на {amount} {currency}",
        "payments.topped_with_suffix": "✅ Баланс пополнен на {amount} {currency} ({suffix})",
        "payments.success_suffix.stars": "Telegram Stars",
        "payments.success_suffix.tg": "Telegram Payments",
        "payments.referral.bonus": "✅ Вы получили {amount} {currency} от вашего реферала <a href='tg://user?id={id}'>{name}</a>",
        "payments.invoice.title.topup": "Пополнение баланса",
        "payments.invoice.desc.topup.stars": "Пополнение на {amount} {currency} через Telegram Stars",
        "payments.invoice.desc.topup.fiat": "Оплата через Telegram Payments (карта)",
        "payments.invoice.label.fiat": "Пополнение на {amount} {currency}",
        "payments.invoice.label.stars": "{stars} ⭐️",
        "payments.already_processed": "Этот платеж уже был обработан ✅",
        "payments.processing_error": "Ошибка при обработке платежа. Попробуйте позже.",

        # === Shop Browsing (Categories / Goods / Item Page) ===
        "shop.categories.title": "🏪 Категории магазина",
        "shop.goods.choose": "🏪 Выберите нужный товар",
        "shop.item.not_found": "Товар не найден",
        "shop.item.title": "🏪 Товар {name}",
        "shop.item.description": "Описание: {description}",
        "shop.item.price": "Цена — {amount} {currency}",
        "shop.item.quantity_unlimited": "Количество — неограниченно",
        "shop.item.quantity_left": "Количество — {count} шт.",
        "shop.insufficient_funds": "❌ Недостаточно средств",
        "shop.out_of_stock": "❌ Товара нет в наличии",
        "shop.purchase.success": "✅ Товар куплен. <b>Баланс</b>: <i>{balance}</i> {currency}\n\n{value}",
        "shop.purchase.processing": "⏳ Обрабатываем покупку...",
        "shop.purchase.fail.user_not_found": "❌ Пользователь не найден в системе",
        "shop.purchase.fail.general": "❌ Ошибка при покупке: {message}",

        # === Purchases ===
        "purchases.title": "Купленные товары:",
        "purchases.pagination.invalid": "Некорректные данные пагинации",
        "purchases.item.not_found": "Покупка не найдена",
        "purchases.item.name": "<b>🧾 Товар</b>: <code>{name}</code>",
        "purchases.item.price": "<b>💵 Цена</b>: <code>{amount}</code> {currency}",
        "purchases.item.datetime": "<b>🕒 Дата покупки</b>: <code>{dt}</code>",
        "purchases.item.unique_id": "<b>🧾 Уникальный ID</b>: <code>{uid}</code>",
        "purchases.item.value": "<b>🔑 Значение</b>:\n<code>{value}</code>",
        "purchases.item.buyer": "<b>Покупатель</b>: <code>{buyer}</code>",

        # === Middleware ===
        "middleware.ban": "⏳ Вы временно заблокированы. Подождите {time} секунд",
        "middleware.above_limits": "⚠️ Слишком много запросов! Вы временно заблокированы.",
        "middleware.waiting": "⏳ Подождите {time} секунд перед следующим действием.",
        "middleware.security.session_outdated": "⚠️ Сессия устарела. Пожалуйста, начните заново.",
        "middleware.security.invalid_data": "❌ Недопустимые данные",
        "middleware.security.blocked": "❌ Доступ заблокирован",
        "middleware.security.not_admin": "⛔ Недостаточно прав",
        "middleware.security.invalid_csrf": "⚠️ Сессия устарела. Пожалуйста, попробуйте снова.",
        "maintenance.active": "🔧 Бот находится на техническом обслуживании. Пожалуйста, попробуйте позже.",

        # === Admin: Maintenance ===
        "admin.menu.maintenance_on": "🔧 Тех. работы: ВКЛ",
        "admin.menu.maintenance_off": "🔧 Тех. работы: ВЫКЛ",
        "admin.maintenance.enabled": "✅ Режим тех. работ включён",
        "admin.maintenance.disabled": "✅ Режим тех. работ выключён",

        # === Errors ===
        "errors.not_subscribed": "Вы не подписались",
        "errors.something_wrong": "❌ Что-то пошло не так. Попробуйте ещё раз.",
        "errors.pagination_invalid": "Некорректные данные пагинации",
        "errors.invalid_data": "❌ Неправильные данные",
        "errors.id_should_be_number": "❌ ID должен быть числом.",
        "errors.channel.telegram_not_found": "Я не могу писать в канал. Добавьте меня админом канала для заливов @{channel} с правом публиковать сообщения.",
        "errors.channel.telegram_forbidden_error": "Канал не найден. Проверьте username канала для заливов @{channel}.",
        "errors.channel.telegram_bad_request": "Не удалось отправить в канал для заливов: {e}",
    },

    "en": {
        # === Common Buttons ===
        "btn.shop": "🏪 Shop",
        "btn.rules": "📜 Rules",
        "btn.profile": "👤 Profile",
        "btn.support": "🆘 Support",
        "btn.channel": "ℹ News channel",
        "btn.admin_menu": "🎛 Admin panel",
        "btn.back": "⬅️ Back",
        "btn.to_menu": "🏠 Menu",
        "btn.close": "✖ Close",
        "btn.buy": "🛒 Buy",
        "btn.yes": "✅ Yes",
        "btn.no": "❌ No",
        "btn.check": "🔄 Check",
        "btn.check_subscription": "🔄 Check subscription",
        "btn.check_payment": "🔄 Check payment",
        "btn.pay": "💳 Pay",
        "btn.pay.crypto": "💎 CryptoPay",
        "btn.pay.stars": "⭐ Telegram Stars",
        "btn.pay.tg": "💸 Telegram Payments",

        # === Admin Buttons (user management shortcuts) ===
        "btn.admin.view_profile": "👁 View profile",
        "btn.admin.promote": "⬆️ Make admin",
        "btn.admin.demote": "⬇️ Remove admin",
        "btn.admin.replenish_user": "💸 Top up balance",
        "btn.admin.deduct_user": "💳 Deduct from balance",
        "btn.admin.block": "🚫 Block",
        "btn.admin.unblock": "✅ Unblock",

        # === Titles / Generic Texts ===
        "menu.title": "⛩️ Main menu",
        "profile.caption": "👤 <b>Profile</b> — <a href='tg://user?id={id}'>{name}</a>",
        "rules.not_set": "❌ Rules have not been added",

        # === Profile ===
        "btn.replenish": "💳 Top up your balance",
        "btn.referral": "🎲 Referral system",
        "btn.purchased": "🎁 Purchased goods",
        "profile.referral_id": "👤 <b>Referral</b> — <code>{id}</code>",

        # === Subscription Flow ===
        "subscribe.prompt": "First, subscribe to the news channel",
        "subscribe.open_channel": "Open channel",

        # === Profile Info Lines ===
        "profile.id": "🆔 <b>ID</b> — <code>{id}</code>",
        "profile.balance": "💳 <b>Balance</b> — <code>{amount}</code> {currency}",
        "profile.total_topup": "💵 <b>Total topped up</b> — <code>{amount}</code> {currency}",
        "profile.purchased_count": "🎁 <b>Purchased items</b> — {count} pcs",
        "profile.registration_date": "🕢 <b>Registered at</b> — <code>{dt}</code>",

        # === Referral ===
        "referral.title": "💚 Referral system",
        "referral.link": "🔗 Link: https://t.me/{bot_username}?start={user_id}",
        "referral.count": "Referrals count: {count}",
        "referral.description": (
            "📔 The referral system lets you earn without any investment. "
            "Share your personal link and you will receive {percent}% of your referrals’ "
            "top-ups to your bot balance."
        ),
        "btn.view_referrals": "👥 My referrals",
        "btn.view_earnings": "💰 My earnings",
        "btn.back_to_referral": "⬅️ Back to referral system",

        "referrals.list.title": "👥 Your referrals:",
        "referrals.list.empty": "You don't have any active referrals yet",
        "referrals.item.format": "ID: {telegram_id} | Earned: {total_earned} {currency}",

        "referral.earnings.title": "💰 Earnings from referral <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>):",
        "referral.earnings.empty": "No earnings from this referral <code>{id}</code> (<a href='tg://user?id={id}'>{name}</a>) yet",
        "referral.earning.format": "{amount} {currency} | {date} | (from {original_amount} {currency})",
        "referral.item.info": ("💰 Earning number: <code>{id}</code>\n"
                               "👤 Referral: <code>{telegram_id}</code> (<a href='tg://user?id={telegram_id}'>{name}</a>)\n"
                               "🔢 Amount: {amount} {currency}\n"
                               "🕘 Date: <code>{date}</code>\n"
                               "💵 From a deposit to {original_amount} {currency}"),

        "all.earnings.title": "💰 All your referral earnings:",
        "all.earnings.empty": "You have no referral earnings yet",
        "all.earning.format": "{amount} {currency} from ID:{referral_id} | {date}",

        "referrals.stats.template": (
            "📊 Referral system statistics:\n\n"
            "👥 Active referrals: {active_count}\n"
            "💰 Total earned: {total_earned} {currency}\n"
            "📈 Total referrals top-ups: {total_original} {currency}\n"
            "🔢 Number of earnings: {earnings_count}"
        ),

        # === Admin: Main Menu ===
        "admin.menu.main": "⛩️ Admin Menu",
        "admin.menu.shop": "🛒 Shop management",
        "admin.menu.goods": "📦 Items management",
        "admin.menu.categories": "📂 Categories management",
        "admin.menu.users": "👥 Users management",
        "admin.menu.broadcast": "📝 Broadcast",
        "admin.menu.roles": "🛡 Role management",
        "admin.menu.rights": "Insufficient permissions",

        # === Admin: Role Management ===
        "admin.roles.list_title": "🛡 System roles:",
        "admin.roles.create": "➕ Create role",
        "admin.roles.edit": "✏️ Edit",
        "admin.roles.delete": "🗑 Delete",
        "admin.roles.detail": "🛡 <b>Role</b>: {name}\n📋 Permissions: {perms}\n👥 Users: {users}",
        "admin.roles.prompt_name": "Enter the role name (max 64 characters):",
        "admin.roles.name_invalid": "⚠️ Invalid name (empty or exceeds 64 characters).",
        "admin.roles.name_exists": "❌ A role with this name already exists",
        "admin.roles.select_perms": "Select permissions for role \"{name}\":",
        "admin.roles.confirm": "✅ Confirm",
        "admin.roles.created": "✅ Role \"{name}\" created",
        "admin.roles.updated": "✅ Role \"{name}\" updated",
        "admin.roles.deleted": "✅ Role deleted",
        "admin.roles.delete_confirm": "Are you sure you want to delete the role \"{name}\"?",
        "admin.roles.delete_fail": "❌ Failed to delete: {error}",
        "admin.roles.perm_denied": "⚠️ Insufficient permissions for this action",
        "admin.roles.assign_prompt": "Select a role for user {id}:",
        "admin.roles.assigned": "✅ Role {role} assigned to {name}",
        "admin.roles.assigned_notify": "ℹ️ Your role has been set to: {role}",
        "admin.roles.edit_name_prompt": "Enter the new role name (or /skip to keep current):",
        "btn.admin.assign_role": "🛡 Assign role",

        # === Admin: User Management ===
        "admin.users.prompt_enter_id": "👤 Enter the user ID to view / edit data",
        "admin.users.invalid_id": "⚠️ Please enter a valid numeric user ID.",
        "admin.users.profile_unavailable": "❌ Profile unavailable (such user never existed)",
        "admin.users.not_found": "❌ User not found",
        "admin.users.cannot_change_owner": "You cannot change the owner’s role",
        "admin.users.referrals": "👥 <b>User referrals</b> — {count}",
        "admin.users.btn.view_referrals": "👥 User's referrals",
        "admin.users.btn.view_earnings": "💰 User's earnings",
        "admin.users.role": "🎛 <b>Role</b> — {role}",
        "admin.users.set_admin.success": "✅ Role assigned to {name}",
        "admin.users.set_admin.notify": "✅ You have been granted the ADMIN role",
        "admin.users.remove_admin.success": "✅ Admin role revoked from {name}",
        "admin.users.remove_admin.notify": "❌ Your ADMIN role has been revoked",
        "admin.users.balance.topped": "✅ {name}'s balance has been topped up by {amount} {currency}",
        "admin.users.balance.topped.notify": "✅ Your balance has been topped up by {amount} {currency}",
        "admin.users.balance.deducted": "✅ Deducted {amount} {currency} from {name}'s balance",
        "admin.users.balance.deducted.notify": "ℹ️ {amount} {currency} has been deducted from your balance",
        "admin.users.balance.insufficient": "❌ Insufficient funds. Current balance: {balance} {currency}",
        "admin.users.blocked.success": "🚫 User {name} has been blocked",
        "admin.users.unblocked.success": "✅ User {name} has been unblocked",
        "admin.users.cannot_block_owner": "❌ Cannot block the owner",
        "admin.users.status.blocked": "🚫 <b>Status</b> — Blocked",

        # === Admin: Shop Management Menu ===
        "admin.shop.menu.title": "⛩️ Shop management",
        "admin.shop.menu.statistics": "📊 Statistics",
        "admin.shop.menu.logs": "📁 Show logs",
        "admin.shop.menu.admins": "👮 Admins",
        "admin.shop.menu.users": "👤 Users",
        "admin.shop.menu.search_bought": "🔎 Search purchased item",

        # === Admin: Categories Management ===
        "admin.categories.menu.title": "⛩️ Categories management",
        "admin.categories.add": "➕ Add category",
        "admin.categories.rename": "✏️ Rename category",
        "admin.categories.delete": "🗑 Delete category",
        "admin.categories.prompt.add": "Enter a new category name:",
        "admin.categories.prompt.delete": "Enter the category name to delete:",
        "admin.categories.prompt.rename.old": "Enter the current category name to rename:",
        "admin.categories.prompt.rename.new": "Enter the new category name:",
        "admin.categories.add.exist": "❌ Category not created (already exists)",
        "admin.categories.add.success": "✅ Category created",
        "admin.categories.delete.not_found": "❌ Category not deleted (does not exist)",
        "admin.categories.delete.success": "✅ Category deleted",
        "admin.categories.rename.not_found": "❌ Category cannot be updated (does not exist)",
        "admin.categories.rename.exist": "❌ Cannot rename (a category with this name already exists)",
        "admin.categories.rename.success": "✅ Category \"{old}\" renamed to \"{new}\"",

        # === Admin: Goods / Items Management (Add / List / Item Info) ===
        "admin.goods.add_position": "➕ add item",
        "admin.goods.add_item": "➕ Add product to item",
        "admin.goods.update_position": "📝 change item",
        "admin.goods.delete_position": "❌ delete item",
        "admin.goods.show_items": "📄 show goods in item",
        "admin.goods.add.prompt.name": "Enter the item name",
        "admin.goods.add.name.exists": "❌ Item cannot be created (it already exists)",
        "admin.goods.add.prompt.description": "Enter item description:",
        "admin.goods.add.prompt.price": "Enter item price (number in {currency}):",
        "admin.goods.add.price.invalid": "⚠️ Invalid price. Please enter a number.",
        "admin.goods.add.prompt.category": "Enter the category the item belongs to:",
        "admin.goods.add.category.not_found": "❌ Item cannot be created (invalid category provided)",
        "admin.goods.add.infinity.question": "Should this item have infinite values? (everyone will receive the same value copy)",
        "admin.goods.add.values.prompt_multi": (
            "Send product values one per message.\n"
            "When finished, press “Add the listed goods”."
        ),
        "admin.goods.add.values.added": "✅ Value “{value}” added to the list ({count} pcs).",
        "admin.goods.add.result.created": "✅ Item has been created.",
        "admin.goods.add.result.added": "📦 Added values: <b>{n}</b>",
        "admin.goods.add.result.skipped_db_dup": "↩️ Skipped (already in DB): <b>{n}</b>",
        "admin.goods.add.result.skipped_batch_dup": "🔁 Skipped (duplicate in input): <b>{n}</b>",
        "admin.goods.add.result.skipped_invalid": "🚫 Skipped (empty/invalid): <b>{n}</b>",
        "admin.goods.add.single.prompt_value": "Enter a single value for the item:",
        "admin.goods.add.single.empty": "⚠️ Value cannot be empty.",
        "admin.goods.add.single.created": "✅ Item created, value added",
        "btn.add_values_finish": "Add the listed goods",
        "admin.goods.position.not_found": "❌ No goods (this item doesn't exist)",
        "admin.goods.list_in_position.empty": "ℹ️ There are no goods in this item yet.",
        "admin.goods.list_in_position.title": "Goods in item:",
        "admin.goods.item.invalid": "Invalid data",
        "admin.goods.item.invalid_id": "Invalid item ID",
        "admin.goods.item.not_found": "Item not found",
        "admin.goods.prompt.enter_item_name": "Enter the item name",
        "admin.goods.menu.title": "⛩️ Items management menu",

        # === Admin: Goods / Items Update Flow ===
        "admin.goods.update.amount.prompt.name": "Enter the item name",
        "admin.goods.update.amount.not_exists": "❌ Unable to add values (item does not exist)",
        "admin.goods.update.amount.infinity_forbidden": "❌ Unable to add values (this item is infinite)",
        "admin.goods.update.values.result.title": "✅ Values added",
        "admin.goods.update.position.invalid": "Item not found.",
        "admin.goods.update.position.exists": "An item with this name already exists.",
        "admin.goods.update.prompt.name": "Enter the item name",
        "admin.goods.update.not_exists": "❌ Item cannot be updated (does not exist)",
        "admin.goods.update.prompt.new_name": "Enter a new item name:",
        "admin.goods.update.prompt.description": "Enter item description:",
        "admin.goods.update.infinity.make.question": "Do you want to make the item infinite?",
        "admin.goods.update.infinity.deny.question": "Do you want to disable infinity?",
        "admin.goods.update.success": "✅ Item updated",

        # === Admin: Goods / Items Delete Flow ===
        "admin.goods.delete.prompt.name": "Enter the item name",
        "admin.goods.delete.position.not_found": "❌ item not deleted (this item doesn't exist)",
        "admin.goods.delete.position.success": "✅ item deleted",
        "admin.goods.item.delete.button": "❌ Delete item",
        "admin.goods.item.already_deleted_or_missing": "Item already deleted or not found",
        "admin.goods.item.deleted": "✅ Item deleted",

        # === Admin: Item Info ===
        "admin.goods.item.info.position": "<b>Item</b>: <code>{name}</code>",
        "admin.goods.item.info.price": "<b>Price</b>: <code>{price}</code> {currency}",
        "admin.goods.item.info.id": "<b>Unique ID</b>: <code>{id}</code>",
        "admin.goods.item.info.value": "<b>Product</b>: <code>{value}</code>",

        # === Admin: Logs ===
        "admin.shop.logs.caption": "Bot logs",
        "admin.shop.logs.empty": "❗️ No logs yet",

        # === Group Notifications ===
        "shop.group.new_upload": "New stock",
        "shop.group.item": "Item",
        "shop.group.count": "Quantity",

        # === Admin: Statistics ===
        "admin.shop.stats.template": (
            "Shop statistics:\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "<b>◽USERS</b>\n"
            "◾️Users in last 24h: {today_users}\n"
            "◾️Total admins: {admins}\n"
            "◾️Total users: {users}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>FUNDS</b>\n"
            "◾Sales in last 24h: {today_orders} {currency}\n"
            "◾Total sold: {all_orders} {currency}\n"
            "◾Top-ups in last 24h: {today_topups} {currency}\n"
            "◾Funds in system: {system_balance} {currency}\n"
            "◾Total top-ups: {all_topups} {currency}\n"
            "➖➖➖➖➖➖➖➖➖➖➖➖➖\n"
            "◽<b>MISC</b>\n"
            "◾Items: {items} pcs\n"
            "◾Positions: {goods} pcs\n"
            "◾Categories: {categories} pcs\n"
            "◾Sold items: {sold_count} pcs"
        ),

        # === Admin: Lists & Broadcast ===
        "admin.shop.admins.title": "👮 Bot admins:",
        "admin.shop.users.title": "Bot users:",
        "admin.shop.bought.prompt_id": "Enter purchased item unique ID",
        "admin.shop.bought.not_found": "❌ Item with given unique ID not found",
        "broadcast.prompt": "Send a message to broadcast:",
        "broadcast.creating": "📤 Starting the newsletter...\n👥 Total users: {ids}",
        "broadcast.progress": (
            "📤 Broadcasting in progress...\n\n\n"
            "📊 Progress: {progress:.1f}%{n}"
            "✅ Sent: {sent}/{total}\n"
            "❌ Errors: {failed}\n"
            "⏱ Time elapsed: {time} sec"),
        "broadcast.done": (
            "✅ Broadcasting is complete! \n\n"
            "📊 Statistics:📊\n"
            "👥 Total: {total}\n"
            "✅ Delivered: {sent}\n"
            "❌ Undelivered: {failed}\n"
            "🚫 Blocked bot: ~{blocked}\n"
            "📈 Success rate: {success}%\n"
            "⏱ Time: {duration} sec"
        ),
        "broadcast.cancel": "❌ The broadcast has been canceled.",
        "broadcast.warning": "No active broadcast",

        # === Payments / Top-up Flow ===
        "payments.replenish_prompt": "Enter top-up amount in {currency}:",
        "payments.replenish_invalid": "❌ Invalid amount. Enter a number from {min_amount} to {max_amount} {currency}.",
        "payments.deduct_prompt": "Enter deduction amount in {currency}:",
        "payments.deduct_invalid": "❌ Invalid amount. Enter a number from {min_amount} to {max_amount} {currency}.",
        "payments.method_choose": "Choose a payment method:",
        "payments.not_configured": "❌ Top-ups are not configured",
        "payments.session_expired": "Payment session has expired. Please start again.",
        "payments.crypto.create_fail": "❌ Failed to create invoice: {error}",
        "payments.crypto.api_error": "❌ CryptoPay API error: {error}",
        "payments.crypto.check_fail": "❌ Payment check failed: {error}",
        "payments.stars.create_fail": "❌ Failed to issue Stars invoice: {error}",
        "payments.fiat.create_fail": "❌ Failed to issue invoice: {error}",
        "payments.no_active_invoice": "❌ No active invoices found. Start top-up again.",
        "payments.invoice_not_found": "❌ Invoice not found. Please start again.",
        "payments.not_paid_yet": "⌛️ Payment is not completed yet.",
        "payments.expired": "❌ Invoice has expired.",
        "payments.invoice.summary": (
            "💵 Top-up amount: {amount} {currency}.\n"
            "⌛️ You have {minutes} minutes to pay.\n"
            "<b>❗️ After paying, press «{button}»</b>"
        ),
        "payments.unable_determine_amount": "❌ Failed to determine the paid amount.",
        "payments.topped_simple": "✅ Balance topped up by {amount} {currency}",
        "payments.topped_with_suffix": "✅ Balance topped up by {amount} {currency} ({suffix})",
        "payments.success_suffix.stars": "Telegram Stars",
        "payments.success_suffix.tg": "Telegram Payments",
        "payments.referral.bonus": "✅ You received {amount} {currency} from your referral <a href='tg://user?id={id}'>{name}</a>",
        "payments.invoice.title.topup": "Balance top-up",
        "payments.invoice.desc.topup.stars": "Top-up {amount} {currency} via Telegram Stars",
        "payments.invoice.desc.topup.fiat": "Pay via Telegram Payments (card)",
        "payments.invoice.label.fiat": "Top-up {amount} {currency}",
        "payments.invoice.label.stars": "{stars} ⭐️",
        "payments.already_processed": "This payment has already been processed ✅",
        "payments.processing_error": "Payment processing error. Please try again later.",

        # === Shop Browsing (Categories / Goods / Item Page) ===
        "shop.categories.title": "🏪 Shop categories",
        "shop.goods.choose": "🏪 Choose a product",
        "shop.item.not_found": "Item not found",
        "shop.item.title": "🏪 Item {name}",
        "shop.item.description": "Description: {description}",
        "shop.item.price": "Price — {amount} {currency}",
        "shop.item.quantity_unlimited": "Quantity — unlimited",
        "shop.item.quantity_left": "Quantity — {count} pcs",
        "shop.insufficient_funds": "❌ Insufficient funds",
        "shop.out_of_stock": "❌ Item is out of stock",
        "shop.purchase.success": "✅ Item purchased. <b>Balance</b>: <i>{balance}</i> {currency}\n\n{value}",
        "shop.purchase.processing": "⏳ Processing the purchase...",
        "shop.purchase.fail.user_not_found": "❌ User not found in the system",
        "shop.purchase.fail.general": "❌ Purchase error: {message}",

        # === Purchases ===
        "purchases.title": "Purchased items:",
        "purchases.pagination.invalid": "Invalid pagination data",
        "purchases.item.not_found": "Purchase not found",
        "purchases.item.name": "<b>🧾 Item</b>: <code>{name}</code>",
        "purchases.item.price": "<b>💵 Price</b>: <code>{amount}</code> {currency}",
        "purchases.item.datetime": "<b>🕒 Purchased at</b>: <code>{dt}</code>",
        "purchases.item.unique_id": "<b>🧾 Unique ID</b>: <code>{uid}</code>",
        "purchases.item.value": "<b>🔑 Value</b>:\n<code>{value}</code>",
        "purchases.item.buyer": "<b>Buyer</b>: <code>{buyer}</code>",

        # === Middleware ===
        "middleware.ban": "⏳ You are temporarily blocked. Wait {time} seconds.",
        "middleware.above_limits": "⚠️ Too many requests! You are temporarily blocked.",
        "middleware.waiting": "⏳ Wait {time} seconds for the next action.",
        "middleware.security.session_outdated": "⚠️ Session is outdated. Please start again.",
        "middleware.security.invalid_data": "❌ Invalid data",
        "middleware.security.blocked": "❌ Access blocked",
        "middleware.security.not_admin": "⛔ Insufficient permissions",
        "middleware.security.invalid_csrf": "⚠️ Session expired. Please try again.",
        "maintenance.active": "🔧 The bot is under maintenance. Please try again later.",

        # === Admin: Maintenance ===
        "admin.menu.maintenance_on": "🔧 Maintenance: ON",
        "admin.menu.maintenance_off": "🔧 Maintenance: OFF",
        "admin.maintenance.enabled": "✅ Maintenance mode enabled",
        "admin.maintenance.disabled": "✅ Maintenance mode disabled",

        # === Errors ===
        "errors.not_subscribed": "You are not subscribed",
        "errors.something_wrong": "❌ Something went wrong. Please try again.",
        "errors.pagination_invalid": "Invalid pagination data",
        "errors.invalid_data": "❌ Invalid data",
        "errors.id_should_be_number": "❌ ID must be a number.",
        "errors.channel.telegram_not_found": "I can't write to the channel. Add me as a channel admin for uploads @{channel} with the right to publish messages.",
        "errors.channel.telegram_forbidden_error": "Channel not found. Check the channel username for uploads @{channel}.",
        "errors.channel.telegram_bad_request": "Failed to send to the channel for uploads: {e}",
        "errors.general_error": "❌ Error: {e}",
    },
}
