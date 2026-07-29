from .main import router as main_router
from .adding_position import router as adding_position_router
from .broadcast import router as broadcast_router
from .categories_management import router as categories_management_router
from .goods_management import router as goods_management_router
from .shop_management import router as shop_management_router
from .update_position import router as update_position_router
from .user_management import router as user_management_router
from .role_management import router as role_management_router
from .promo_management import router as promo_management_router
from .sale_management import router as sale_management_router
from .start_image_settings import router as start_image_settings_router

from aiogram import Router

router = Router()
router.include_router(main_router)
router.include_router(start_image_settings_router)
router.include_router(adding_position_router)
router.include_router(broadcast_router)
router.include_router(categories_management_router)
router.include_router(goods_management_router)
router.include_router(shop_management_router)
router.include_router(update_position_router)
router.include_router(user_management_router)
router.include_router(role_management_router)
router.include_router(promo_management_router)
router.include_router(sale_management_router)
