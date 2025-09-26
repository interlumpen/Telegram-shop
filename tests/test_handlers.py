import pytest
import datetime
import warnings
from unittest.mock import MagicMock, AsyncMock, patch
from decimal import Decimal

from aiogram.types import Message, CallbackQuery, User, Chat, ChatMember
from aiogram.enums import ChatType, ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.handlers.user.main import start, back_to_menu_callback_handler, rules_callback_handler, \
    profile_callback_handler
from bot.handlers.user.balance_and_payment import replenish_balance_callback_handler, replenish_balance_amount
from bot.states.payment_state import BalanceStates

# Filter Pydantic v2 deprecation warnings from unittest.mock
warnings.filterwarnings("ignore", category=DeprecationWarning,
                       message="The `__fields__` attribute is deprecated, use `model_fields` instead.")
warnings.filterwarnings("ignore", category=DeprecationWarning,
                       module="pydantic._internal._model_construction")

# Add pytest mark to ignore warnings at the module level
pytestmark = [
    pytest.mark.filterwarnings("ignore:The `__fields__` attribute is deprecated:DeprecationWarning"),
    pytest.mark.filterwarnings("ignore::pydantic.warnings.PydanticDeprecatedSince20")
]


class TestUserMainHandlers:
    """Test suite for main user handlers"""

    @pytest.fixture
    def mock_message(self):
        """Create a mock message"""
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=User)
        message.from_user.id = 12345
        message.from_user.first_name = "Test User"
        message.chat = MagicMock(spec=Chat)
        message.chat.type = ChatType.PRIVATE
        message.text = "/start"
        message.answer = AsyncMock()
        message.delete = AsyncMock()
        message.bot = AsyncMock()
        return message

    @pytest.fixture
    def mock_callback(self):
        """Create a mock callback query"""
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=User)
        callback.from_user.id = 12345
        callback.from_user.first_name = "Test User"
        callback.message = MagicMock()
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        callback.data = "test_callback"
        callback.bot = AsyncMock()
        return callback

    @pytest.fixture
    def mock_state(self):
        """Create a mock FSM context"""
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()
        state.get_data = AsyncMock(return_value={})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        return state

    @pytest.mark.asyncio
    async def test_start_handler_new_user(self, mock_message, mock_state):
        """Test start handler for new user"""
        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user') as mock_create_user:
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                        with patch('bot.handlers.user.main.localize', return_value="Welcome!"):
                            with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '99999'):
                                with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                                    with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                        mock_main_menu.return_value = MagicMock()

                                        await start(mock_message, mock_state)

                                        # Verify user creation was called
                                        mock_create_user.assert_called_once()
                                        call_args = mock_create_user.call_args[1]
                                        assert call_args['telegram_id'] == 12345
                                        assert call_args['role'] == 1  # Not owner
                                        assert call_args['referral_id'] is None

                                        # Verify menu was shown
                                        mock_message.answer.assert_called_once_with("Welcome!",
                                                                                    reply_markup=mock_main_menu.return_value)
                                        mock_message.delete.assert_called_once()
                                        mock_state.clear.assert_called()

    @pytest.mark.asyncio
    async def test_start_handler_owner_user(self, mock_message, mock_state):
        """Test start handler for owner user"""
        with patch('bot.handlers.user.main.select_max_role_id', return_value=3):
            with patch('bot.handlers.user.main.create_user') as mock_create_user:
                with patch('bot.handlers.user.main.check_role', return_value=3):
                    with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                        with patch('bot.handlers.user.main.localize', return_value="Welcome Admin!"):
                            with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '12345'):  # Same as user ID
                                with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                                    with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                        mock_main_menu.return_value = MagicMock()

                                        await start(mock_message, mock_state)

                                        # Verify owner gets max role
                                        call_args = mock_create_user.call_args[1]
                                        assert call_args['role'] == 3  # Max role for owner

    @pytest.mark.asyncio
    async def test_start_handler_with_referral(self, mock_message, mock_state):
        """Test start handler with referral parameter"""
        mock_message.text = "/start 67890"

        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user') as mock_create_user:
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                        with patch('bot.handlers.user.main.localize', return_value="Welcome!"):
                            with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '99999'):
                                with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                                    with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                        mock_main_menu.return_value = MagicMock()

                                        await start(mock_message, mock_state)

                                        # Verify referral ID was captured
                                        call_args = mock_create_user.call_args[1]
                                        assert call_args['referral_id'] == 67890

    @pytest.mark.asyncio
    async def test_start_handler_self_referral_ignored(self, mock_message, mock_state):
        """Test that self-referral is ignored"""
        mock_message.text = "/start 12345"  # Same as user ID

        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user') as mock_create_user:
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                        with patch('bot.handlers.user.main.localize', return_value="Welcome!"):
                            with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '99999'):
                                with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                                    with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                        mock_main_menu.return_value = MagicMock()

                                        await start(mock_message, mock_state)

                                        # Self-referral should be None
                                        call_args = mock_create_user.call_args[1]
                                        assert call_args['referral_id'] is None

    @pytest.mark.asyncio
    async def test_start_handler_with_channel_subscription_required(self, mock_message, mock_state):
        """Test start handler when channel subscription is required"""
        # Mock channel member as not subscribed
        mock_chat_member = MagicMock(spec=ChatMember)
        mock_message.bot.get_chat_member.return_value = mock_chat_member

        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user'):
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.check_sub_channel', return_value=False):
                        with patch('bot.handlers.user.main.check_sub') as mock_check_sub:
                            with patch('bot.handlers.user.main.localize', return_value="Please subscribe"):
                                with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '99999'):
                                    with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL',
                                               'https://t.me/testchannel'):
                                        mock_check_sub.return_value = MagicMock()

                                        await start(mock_message, mock_state)

                                        # Should prompt for subscription
                                        mock_message.answer.assert_called_once_with(
                                            "Please subscribe",
                                            reply_markup=mock_check_sub.return_value
                                        )
                                        mock_message.delete.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_handler_channel_check_error(self, mock_message, mock_state):
        """Test start handler when channel check fails"""
        mock_message.bot.get_chat_member.side_effect = TelegramBadRequest(method=None, message="Channel not found")

        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user'):
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                        with patch('bot.handlers.user.main.localize', return_value="Welcome!"):
                            with patch('bot.handlers.user.main.EnvKeys.OWNER_ID', '99999'):
                                with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', 'https://t.me/privatechannel'):
                                    with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                        with patch('bot.handlers.user.main.logger') as mock_logger:
                                            mock_main_menu.return_value = MagicMock()

                                            await start(mock_message, mock_state)

                                            # Should continue to main menu despite channel error
                                            mock_message.answer.assert_called_once_with(
                                                "Welcome!",
                                                reply_markup=mock_main_menu.return_value
                                            )
                                            mock_logger.warning.assert_called()

    @pytest.mark.asyncio
    async def test_start_handler_non_private_chat(self, mock_message, mock_state):
        """Test start handler in non-private chat (should be ignored)"""
        mock_message.chat.type = ChatType.GROUP

        result = await start(mock_message, mock_state)

        # Should return early without doing anything
        assert result is None
        mock_message.answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_back_to_menu_callback_handler(self, mock_callback, mock_state):
        """Test back to menu callback handler"""
        mock_user_data = {'role_id': 1, 'balance': Decimal('100')}

        with patch('bot.handlers.user.main.check_user_cached', return_value=mock_user_data):
            with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                with patch('bot.handlers.user.main.localize', return_value="Main Menu"):
                    with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                        with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                            mock_main_menu.return_value = MagicMock()

                            await back_to_menu_callback_handler(mock_callback, mock_state)

                            mock_callback.message.edit_text.assert_called_once_with(
                                "Main Menu",
                                reply_markup=mock_main_menu.return_value
                            )
                            mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_back_to_menu_callback_handler_new_user(self, mock_callback, mock_state):
        """Test back to menu callback handler for new user"""
        # First call returns None (user doesn't exist), second call returns user data after creation
        mock_user_data = {'role_id': 1}

        with patch('bot.handlers.user.main.check_user_cached', side_effect=[None, mock_user_data]) as mock_check:
            with patch('bot.handlers.user.main.create_user') as mock_create_user:
                with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                    with patch('bot.handlers.user.main.localize', return_value="Main Menu"):
                        with patch('bot.handlers.user.main.EnvKeys.CHANNEL_URL', None):
                            with patch('bot.handlers.user.main.EnvKeys.HELPER_ID', None):
                                mock_main_menu.return_value = MagicMock()

                                await back_to_menu_callback_handler(mock_callback, mock_state)

                                # Should create user first
                                mock_create_user.assert_called_once()
                                call_args = mock_create_user.call_args[1]
                                assert call_args['telegram_id'] == 12345
                                assert call_args['role'] == 1

                                # Should call check_user_cached twice: first to check if user exists, second after creation
                                assert mock_check.call_count == 2

    @pytest.mark.asyncio
    async def test_rules_callback_handler_with_rules(self, mock_callback, mock_state):
        """Test rules callback handler when rules are configured"""
        with patch('bot.handlers.user.main.EnvKeys.RULES', 'Bot rules here'):
            with patch('bot.handlers.user.main.back') as mock_back:
                mock_back.return_value = MagicMock()

                await rules_callback_handler(mock_callback, mock_state)

                mock_callback.message.edit_text.assert_called_once_with(
                    "Bot rules here",
                    reply_markup=mock_back.return_value
                )
                mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_rules_callback_handler_no_rules(self, mock_callback, mock_state):
        """Test rules callback handler when no rules are set"""
        with patch('bot.handlers.user.main.EnvKeys.RULES', None):
            with patch('bot.handlers.user.main.localize', return_value="Rules not set"):
                await rules_callback_handler(mock_callback, mock_state)

                mock_callback.answer.assert_called_once_with("Rules not set")
                mock_callback.message.edit_text.assert_not_called()
                mock_state.clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_profile_callback_handler(self, mock_callback, mock_state):
        """Test profile callback handler"""
        mock_user_data = {
            'balance': Decimal('250.50'),
            'role_id': 1
        }

        with patch('bot.handlers.user.main.check_user_cached', return_value=mock_user_data):
            with patch('bot.handlers.user.main.select_user_operations', return_value=[100, 150, 50]):
                with patch('bot.handlers.user.main.select_user_items', return_value=5):
                    with patch('bot.handlers.user.main.profile_keyboard') as mock_profile_keyboard:
                        with patch('bot.handlers.user.main.localize') as mock_localize:
                            with patch('bot.handlers.user.main.EnvKeys.PAY_CURRENCY', 'USD'):
                                with patch('bot.handlers.user.main.EnvKeys.REFERRAL_PERCENT', 10):
                                    mock_profile_keyboard.return_value = MagicMock()
                                    mock_localize.side_effect = lambda key, **kwargs: f"localized_{key}"

                                    await profile_callback_handler(mock_callback, mock_state)

                                    # Verify profile keyboard was created with correct parameters
                                    mock_profile_keyboard.assert_called_once_with(10, 5)

                                    # Verify message was edited
                                    mock_callback.message.edit_text.assert_called_once()
                                    call_args = mock_callback.message.edit_text.call_args
                                    assert 'parse_mode' in call_args[1]
                                    assert call_args[1]['parse_mode'] == 'HTML'

                                    mock_state.clear.assert_called_once()


class TestBalanceAndPaymentHandlers:
    """Test suite for balance and payment handlers"""

    @pytest.fixture
    def mock_callback(self):
        """Create a mock callback query"""
        callback = MagicMock(spec=CallbackQuery)
        callback.from_user = MagicMock(spec=User)
        callback.from_user.id = 12345
        callback.message = MagicMock()
        callback.message.edit_text = AsyncMock()
        callback.answer = AsyncMock()
        return callback

    @pytest.fixture
    def mock_message(self):
        """Create a mock message"""
        message = MagicMock(spec=Message)
        message.from_user = MagicMock(spec=User)
        message.from_user.id = 12345
        message.text = "100"
        message.answer = AsyncMock()
        return message

    @pytest.fixture
    def mock_state(self):
        """Create a mock FSM context"""
        state = AsyncMock(spec=FSMContext)
        state.clear = AsyncMock()
        state.get_data = AsyncMock(return_value={'amount': 100})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        return state

    @pytest.mark.asyncio
    async def test_replenish_balance_callback_handler_enabled(self, mock_callback, mock_state):
        """Test replenish balance callback when payment methods are enabled"""
        with patch('bot.handlers.user.balance_and_payment._any_payment_method_enabled', return_value=True):
            with patch('bot.handlers.user.balance_and_payment.localize', return_value="Enter amount"):
                with patch('bot.handlers.user.balance_and_payment.back') as mock_back:
                    with patch('bot.handlers.user.balance_and_payment.EnvKeys.PAY_CURRENCY', 'USD'):
                        mock_back.return_value = MagicMock()

                        await replenish_balance_callback_handler(mock_callback, mock_state)

                        mock_callback.message.edit_text.assert_called_once_with(
                            "Enter amount",
                            reply_markup=mock_back.return_value
                        )
                        mock_state.set_state.assert_called_once_with(BalanceStates.waiting_amount)

    @pytest.mark.asyncio
    async def test_replenish_balance_callback_handler_disabled(self, mock_callback, mock_state):
        """Test replenish balance callback when payment methods are disabled"""
        with patch('bot.handlers.user.balance_and_payment._any_payment_method_enabled', return_value=False):
            with patch('bot.handlers.user.balance_and_payment.localize', return_value="Payments not configured"):
                await replenish_balance_callback_handler(mock_callback, mock_state)

                mock_callback.answer.assert_called_once_with(
                    "Payments not configured",
                    show_alert=True
                )
                mock_callback.message.edit_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_replenish_balance_amount_valid(self, mock_message, mock_state):
        """Test replenish balance with valid amount"""
        mock_message.text = "150"

        with patch('bot.handlers.user.balance_and_payment.validate_money_amount', return_value=Decimal('150')):
            with patch('bot.handlers.user.balance_and_payment.get_payment_choice') as mock_payment_choice:
                with patch('bot.handlers.user.balance_and_payment.localize', return_value="Choose payment method"):
                    mock_payment_choice.return_value = MagicMock()

                    await replenish_balance_amount(mock_message, mock_state)

                    # Verify amount was stored
                    mock_state.update_data.assert_called_once_with(amount=150)

                    # Verify payment choice was shown
                    mock_message.answer.assert_called_once_with(
                        "Choose payment method",
                        reply_markup=mock_payment_choice.return_value
                    )

                    # Verify state transition
                    mock_state.set_state.assert_called_once_with(BalanceStates.waiting_payment)

    @pytest.mark.asyncio
    async def test_replenish_balance_amount_invalid(self, mock_message, mock_state):
        """Test replenish balance with invalid amount"""
        mock_message.text = "invalid_amount"

        with patch('bot.handlers.user.balance_and_payment.validate_money_amount',
                   side_effect=ValueError("Invalid amount")):
            with patch('bot.handlers.user.balance_and_payment.back') as mock_back:
                with patch('bot.handlers.user.balance_and_payment.localize', return_value="Invalid amount"):
                    with patch('bot.handlers.user.balance_and_payment.EnvKeys.MIN_AMOUNT', '10'):
                        with patch('bot.handlers.user.balance_and_payment.EnvKeys.MAX_AMOUNT', '1000'):
                            with patch('bot.handlers.user.balance_and_payment.EnvKeys.PAY_CURRENCY', 'USD'):
                                mock_back.return_value = MagicMock()

                                await replenish_balance_amount(mock_message, mock_state)

                                mock_message.answer.assert_called_once_with(
                                    "Invalid amount",
                                    reply_markup=mock_back.return_value
                                )

                                # State should not be updated or changed
                                mock_state.update_data.assert_not_called()
                                mock_state.set_state.assert_not_called()


class TestStates:
    """Test suite for FSM states"""

    def test_balance_states_definition(self):
        """Test that BalanceStates are properly defined"""
        assert hasattr(BalanceStates, 'waiting_amount')
        assert hasattr(BalanceStates, 'waiting_payment')

        # States should be State instances
        from aiogram.filters.state import State
        assert isinstance(BalanceStates.waiting_amount, State)
        assert isinstance(BalanceStates.waiting_payment, State)

    def test_balance_states_group(self):
        """Test BalanceStates group properties"""
        from aiogram.filters.state import StatesGroup
        assert issubclass(BalanceStates, StatesGroup)

        # Should have correct number of states
        states = [attr for attr in dir(BalanceStates)
                  if not attr.startswith('_') and attr not in ['get_root', '__class__']]
        assert len(states) >= 2  # At least waiting_amount and waiting_payment


class TestHandlerIntegration:
    """Integration tests for handlers"""

    @pytest.mark.asyncio
    async def test_complete_user_flow(self):
        """Test a complete user flow from start to profile"""
        # Mock user
        mock_user = MagicMock()
        mock_user.id = 12345
        mock_user.first_name = "Test User"

        # Mock message for /start
        mock_start_message = MagicMock(spec=Message)
        mock_start_message.from_user = mock_user
        mock_start_message.chat = MagicMock()
        mock_start_message.chat.type = ChatType.PRIVATE
        mock_start_message.text = "/start"
        mock_start_message.answer = AsyncMock()
        mock_start_message.delete = AsyncMock()
        mock_start_message.bot = AsyncMock()

        # Mock callback for profile
        mock_profile_callback = MagicMock(spec=CallbackQuery)
        mock_profile_callback.from_user = mock_user
        mock_profile_callback.data = "profile"
        mock_profile_callback.message = MagicMock()
        mock_profile_callback.message.edit_text = AsyncMock()

        mock_state = AsyncMock(spec=FSMContext)

        mock_user_data = {
            'balance': Decimal('100.00'),
            'role_id': 1
        }

        with patch('bot.handlers.user.main.select_max_role_id', return_value=2):
            with patch('bot.handlers.user.main.create_user'):
                with patch('bot.handlers.user.main.check_role', return_value=1):
                    with patch('bot.handlers.user.main.check_user_cached', return_value=mock_user_data):
                        with patch('bot.handlers.user.main.select_user_operations', return_value=[50, 50]):
                            with patch('bot.handlers.user.main.select_user_items', return_value=3):
                                with patch('bot.handlers.user.main.main_menu') as mock_main_menu:
                                    with patch('bot.handlers.user.main.profile_keyboard') as mock_profile_keyboard:
                                        with patch('bot.handlers.user.main.localize') as mock_localize:
                                            with patch('bot.handlers.user.main.EnvKeys') as mock_env:
                                                mock_env.OWNER_ID = '99999'
                                                mock_env.CHANNEL_URL = None
                                                mock_env.HELPER_ID = None
                                                mock_env.PAY_CURRENCY = 'USD'
                                                mock_env.REFERRAL_PERCENT = 5

                                                mock_main_menu.return_value = MagicMock()
                                                mock_profile_keyboard.return_value = MagicMock()
                                                mock_localize.side_effect = lambda key, **kwargs: f"localized_{key}"

                                                # Test /start
                                                await start(mock_start_message, mock_state)
                                                mock_start_message.answer.assert_called_once()

                                                # Test profile view
                                                await profile_callback_handler(mock_profile_callback, mock_state)
                                                mock_profile_callback.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_payment_flow_validation(self):
        """Test payment flow with various validations"""
        mock_callback = MagicMock(spec=CallbackQuery)
        mock_callback.message = MagicMock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_message = MagicMock(spec=Message)
        mock_message.text = "50"
        mock_message.answer = AsyncMock()

        mock_state = AsyncMock(spec=FSMContext)

        with patch('bot.handlers.user.balance_and_payment._any_payment_method_enabled', return_value=True):
            with patch('bot.handlers.user.balance_and_payment.validate_money_amount', return_value=Decimal('50')):
                with patch('bot.handlers.user.balance_and_payment.get_payment_choice') as mock_payment_choice:
                    with patch('bot.handlers.user.balance_and_payment.localize') as mock_localize:
                        with patch('bot.handlers.user.balance_and_payment.back') as mock_back:
                            mock_payment_choice.return_value = MagicMock()
                            mock_back.return_value = MagicMock()
                            mock_localize.side_effect = lambda key, **kwargs: f"localized_{key}"

                            # Test starting replenishment
                            await replenish_balance_callback_handler(mock_callback, mock_state)
                            mock_state.set_state.assert_called_with(BalanceStates.waiting_amount)

                            # Test entering valid amount
                            await replenish_balance_amount(mock_message, mock_state)
                            mock_state.update_data.assert_called_with(amount=50)
                            mock_state.set_state.assert_called_with(BalanceStates.waiting_payment)
