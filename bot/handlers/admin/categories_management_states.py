from aiogram import Router, F
from aiogram.types import CallbackQuery, Message

from bot.i18n import localize
from bot.database.models import Permission
from bot.database.methods import check_category, create_category, delete_category, update_category
from bot.keyboards.inline import back, simple_buttons
from bot.filters import HasPermissionFilter
from bot.logger_mesh import audit_logger
from bot.misc import CategoryRequest
from bot.states import CategoryFSM

router = Router()


@router.callback_query(F.data == 'categories_management', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def categories_callback_handler(call: CallbackQuery):
    """
    Opens the categories management submenu.
    """
    actions = [
        (localize("admin.categories.add"), "add_category"),
        (localize("admin.categories.rename"), "update_category"),
        (localize("admin.categories.delete"), "delete_category"),
        (localize("btn.back"), "console"),
    ]
    await call.message.edit_text(
        localize("admin.categories.menu.title"),
        reply_markup=simple_buttons(actions, per_row=1),
    )


@router.callback_query(F.data == 'add_category', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def add_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for a new category name.
    """
    await call.message.edit_text(
        localize("admin.categories.prompt.add"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_add_category)


@router.message(CategoryFSM.waiting_add_category, F.text)
async def process_category_for_add(message: Message, state):
    """Creates a category if it doesn't exist yet."""
    try:
        # Validate category name
        category_request = CategoryRequest(name=message.text.strip())
        category_name = category_request.sanitize_name()

        if check_category(category_name):
            await message.answer(
                localize("admin.categories.add.exist"),
                reply_markup=back("categories_management"),
            )
        else:
            create_category(category_name)
            await message.answer(
                localize("admin.categories.add.success"),
                reply_markup=back("categories_management"),
            )

            admin_info = await message.bot.get_chat(message.from_user.id)
            audit_logger.info(
                f'Admin {message.from_user.id} ({admin_info.first_name}) created category "{category_name}"'
            )

    except Exception as e:
        await message.answer(
            localize("errors.invalid_data"),
            reply_markup=back("categories_management"),
        )
        audit_logger.error(f"Category creation error: {e}")

    await state.clear()


@router.callback_query(F.data == 'delete_category', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def delete_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for a category name to delete.
    """
    await call.message.edit_text(
        localize("admin.categories.prompt.delete"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_delete_category)


# --- Handle category deletion
@router.message(CategoryFSM.waiting_delete_category, F.text)
async def process_category_for_delete(message: Message, state):
    """
    Deletes a category by name if it exists.
    """
    category_name = message.text.strip()

    if not check_category(category_name):
        await message.answer(
            localize("admin.categories.delete.not_found"),
            reply_markup=back("categories_management"),
        )
    else:
        delete_category(category_name)
        await message.answer(
            localize("admin.categories.delete.success"),
            reply_markup=back("categories_management"),
        )
        admin_info = await message.bot.get_chat(message.from_user.id)
        audit_logger.info(
            f'Admin {message.from_user.id} ({admin_info.first_name}) deleted category "{category_name}"'
        )

    await state.clear()


@router.callback_query(F.data == 'update_category', HasPermissionFilter(permission=Permission.SHOP_MANAGE))
async def update_category_callback_handler(call: CallbackQuery, state):
    """
    Asks admin for current category name before renaming.
    """
    await call.message.edit_text(
        localize("admin.categories.prompt.rename.old"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_update_category)


@router.message(CategoryFSM.waiting_update_category, F.text)
async def check_category_for_update(message: Message, state):
    """
    Verifies the category exists, then prompts for a new name.
    """
    old_name = message.text.strip()

    if not check_category(old_name):
        await message.answer(
            localize("admin.categories.rename.not_found"),
            reply_markup=back("categories_management"),
        )
        await state.clear()
        return

    await state.update_data(old_category=old_name)
    await message.answer(
        localize("admin.categories.prompt.rename.new"),
        reply_markup=back("categories_management"),
    )
    await state.set_state(CategoryFSM.waiting_update_category_name)


@router.message(CategoryFSM.waiting_update_category_name, F.text)
async def check_category_name_for_update(message: Message, state):
    """
    Renames a category to the new name.
    """
    new_name = message.text.strip()
    data = await state.get_data()
    old_name = data.get("old_category")

    if check_category(new_name):
        await message.answer(
            localize("admin.categories.rename.exist"),
            reply_markup=back("categories_management"),
        )
        await state.clear()
        return

    update_category(old_name, new_name)
    await message.answer(
        localize("admin.categories.rename.success", old=old_name, new=new_name),
        reply_markup=back("categories_management"),
    )

    admin_info = await message.bot.get_chat(message.from_user.id)
    audit_logger.info(
        f'Admin {message.from_user.id} ({admin_info.first_name}) renamed category "{old_name}" to "{new_name}"'
    )

    await state.clear()
