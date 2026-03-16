from .main import router as main_router
from .adding_position_states import router as adding_position_states_router
from .broadcast import router as broadcast_router
from .categories_management_states import router as categories_management_router
from .goods_management_states import router as goods_management_router
from .shop_management_states import router as shop_management_router
from .update_position_states import router as update_position_router
from .user_management_states import router as user_management_router
from .role_management_states import router as role_management_router
from .promo_management_states import router as promo_management_router

from aiogram import Router

router = Router()
router.include_router(main_router)
router.include_router(adding_position_states_router)
router.include_router(broadcast_router)
router.include_router(categories_management_router)
router.include_router(goods_management_router)
router.include_router(shop_management_router)
router.include_router(update_position_router)
router.include_router(user_management_router)
router.include_router(role_management_router)
router.include_router(promo_management_router)
