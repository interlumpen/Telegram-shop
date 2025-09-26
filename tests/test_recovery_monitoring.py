import pytest
import asyncio
import json
from unittest.mock import MagicMock, AsyncMock, patch, mock_open
from datetime import datetime, timedelta
from decimal import Decimal
from aiohttp.test_utils import AioHTTPTestCase
from aiohttp import web

from bot.misc.recovery import RecoveryManager, StateManager
from bot.misc.monitoring import MonitoringServer
from bot.database.models import Payments


class TestRecoveryManager:
    """Test suite for recovery manager functionality"""

    @pytest.fixture
    def mock_bot(self):
        """Create a mock bot instance"""
        bot = MagicMock()
        # Create a proper mock result for get_me that returns a coroutine
        mock_me_result = MagicMock()
        mock_me_result.username = "testbot"
        mock_me_result.id = 123456

        # Make sure get_me returns a coroutine
        async def mock_get_me():
            return mock_me_result

        bot.get_me = AsyncMock(return_value=mock_me_result)
        bot.send_message = AsyncMock(return_value=True)

        return bot

    @pytest.fixture
    def recovery_manager(self, mock_bot):
        """Create a RecoveryManager instance"""
        return RecoveryManager(mock_bot)

    def test_recovery_manager_initialization(self, mock_bot):
        """Test recovery manager initialization"""
        manager = RecoveryManager(mock_bot)
        assert manager.bot == mock_bot
        assert manager.recovery_tasks == []
        assert manager.running == False

    @pytest.mark.asyncio
    async def test_start_recovery_manager(self, recovery_manager):
        """Test starting the recovery manager"""

        async def mock_coro():
            await asyncio.sleep(0.01)  # Short delay to avoid immediate completion

        with patch.object(recovery_manager, 'recover_pending_payments', new_callable=AsyncMock) as mock_payments:
            with patch.object(recovery_manager, 'recover_interrupted_broadcasts',
                              new_callable=AsyncMock) as mock_broadcasts:
                with patch.object(recovery_manager, 'periodic_health_check', new_callable=AsyncMock) as mock_health:
                    mock_payments.return_value = None
                    mock_broadcasts.return_value = None
                    mock_health.return_value = None

                    await recovery_manager.start()

                    assert recovery_manager.running == True
                    assert len(recovery_manager.recovery_tasks) == 3

    @pytest.mark.asyncio
    async def test_stop_recovery_manager(self, recovery_manager):
        """Test stopping the recovery manager"""

        async def mock_long_coro():
            try:
                await asyncio.sleep(10)  # Long delay to ensure cancellation works
            except asyncio.CancelledError:
                raise

        # Start first
        with patch.object(recovery_manager, 'recover_pending_payments', new_callable=AsyncMock) as mock_payments:
            with patch.object(recovery_manager, 'recover_interrupted_broadcasts',
                              new_callable=AsyncMock) as mock_broadcasts:
                with patch.object(recovery_manager, 'periodic_health_check', new_callable=AsyncMock) as mock_health:
                    # Set up side effects to simulate long-running tasks
                    mock_payments.side_effect = mock_long_coro
                    mock_broadcasts.side_effect = mock_long_coro
                    mock_health.side_effect = mock_long_coro

                    await recovery_manager.start()

        await recovery_manager.stop()

        assert recovery_manager.running == False
        # All tasks should be cancelled
        for task in recovery_manager.recovery_tasks:
            assert task.cancelled()

    @pytest.mark.asyncio
    async def test_safe_run_normal_execution(self, recovery_manager):
        """Test safe_run with normal coroutine execution"""

        async def normal_coro():
            return "success"

        result = await recovery_manager._safe_run(normal_coro())
        # Should complete without issues (no return value expected)

    @pytest.mark.asyncio
    async def test_safe_run_exception_handling(self, recovery_manager):
        """Test safe_run exception handling"""

        async def failing_coro():
            raise ValueError("Test error")

        with patch('bot.misc.recovery.logger') as mock_logger:
            # Should not raise, but log the error
            await recovery_manager._safe_run(failing_coro())
            mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_safe_run_cancellation(self, recovery_manager):
        """Test safe_run handling of cancellation"""

        async def cancellable_coro():
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                # Properly handle cancellation to avoid warnings
                raise

        # Create task and immediately cancel to test cancellation handling
        task = asyncio.create_task(recovery_manager._safe_run(cancellable_coro()))

        # Give the task a tiny moment to start
        await asyncio.sleep(0.001)

        # Cancel the task
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_check_and_process_payment_cryptopay_paid(self, recovery_manager):
        """Test processing a paid CryptoPay payment"""
        # Mock payment object
        payment = MagicMock()
        payment.id = 1
        payment.user_id = 12345
        payment.amount = Decimal("100.00")
        payment.provider = "cryptopay"
        payment.external_id = "crypto_123"
        payment.currency = "USD"

        with patch('bot.misc.recovery.EnvKeys.CRYPTO_PAY_TOKEN', 'test_token'):
            with patch('bot.misc.recovery.CryptoPayAPI') as mock_crypto_api:
                with patch('bot.misc.recovery.process_payment_with_referral') as mock_process:
                    with patch('bot.misc.recovery.EnvKeys.REFERRAL_PERCENT', 10):
                        # Mock crypto API response
                        crypto_instance = mock_crypto_api.return_value
                        crypto_instance.get_invoice = AsyncMock(return_value={"status": "paid"})

                        # Mock successful payment processing
                        mock_process.return_value = (True, "success")

                        # Mock localization
                        with patch('bot.misc.recovery.localize', return_value="Payment confirmed"):
                            await recovery_manager._check_and_process_payment(payment)

                            # Verify crypto API was called
                            crypto_instance.get_invoice.assert_called_once_with("crypto_123")

                            # Verify payment processing was called
                            mock_process.assert_called_once_with(
                                user_id=12345,
                                amount=Decimal("100.00"),
                                provider="cryptopay",
                                external_id="crypto_123",
                                referral_percent=10
                            )

                            # Verify user notification
                            recovery_manager.bot.send_message.assert_called_once_with(
                                12345,
                                "Payment confirmed"
                            )

    @pytest.mark.asyncio
    async def test_check_and_process_payment_expired(self, recovery_manager):
        """Test processing an expired payment"""
        payment = MagicMock()
        payment.id = 1
        payment.provider = "cryptopay"
        payment.external_id = "crypto_123"

        with patch('bot.misc.recovery.EnvKeys.CRYPTO_PAY_TOKEN', 'test_token'):
            with patch('bot.misc.recovery.CryptoPayAPI') as mock_crypto_api:
                with patch('bot.misc.recovery.Database') as mock_db:
                    # Mock crypto API response
                    crypto_instance = mock_crypto_api.return_value
                    crypto_instance.get_invoice = AsyncMock(return_value={"status": "expired"})

                    # Mock database session with proper context manager
                    mock_session = MagicMock()
                    mock_query = MagicMock()
                    mock_filter = MagicMock()

                    mock_session.query.return_value = mock_query
                    mock_query.filter.return_value = mock_filter
                    mock_filter.update.return_value = None

                    # Mock the context manager for Database().session()
                    mock_db_instance = MagicMock()
                    mock_db_instance.session.return_value.__enter__.return_value = mock_session
                    mock_db_instance.session.return_value.__exit__.return_value = None
                    mock_db.return_value = mock_db_instance

                    await recovery_manager._check_and_process_payment(payment)

                    # Verify payment was marked as failed
                    mock_filter.update.assert_called_once_with({"status": "failed"})

    @pytest.mark.asyncio
    async def test_check_and_process_payment_error_handling(self, recovery_manager):
        """Test error handling in payment processing"""
        payment = MagicMock()
        payment.id = 1
        payment.provider = "cryptopay"
        payment.external_id = "crypto_123"

        with patch('bot.misc.recovery.EnvKeys.CRYPTO_PAY_TOKEN', 'test_token'):
            with patch('bot.misc.recovery.CryptoPayAPI') as mock_crypto_api:
                with patch('bot.misc.recovery.logger') as mock_logger:
                    # Mock crypto API to raise an exception
                    crypto_instance = mock_crypto_api.return_value
                    crypto_instance.get_invoice = AsyncMock(side_effect=Exception("API Error"))

                    await recovery_manager._check_and_process_payment(payment)

                    # Should log the error
                    mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_recover_interrupted_broadcasts(self, recovery_manager):
        """Test recovering interrupted broadcasts"""
        mock_cache_manager = AsyncMock()
        broadcast_state = {
            "user_ids": [1, 2, 3],
            "sent_count": 1,
            "message": "Test broadcast"
        }
        # Ensure get returns an awaitable
        mock_cache_manager.get = AsyncMock(return_value=broadcast_state)

        # Need to patch both the module-level import and the local import
        with patch('bot.misc.recovery.get_cache_manager', return_value=mock_cache_manager):
            with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
                with patch.object(recovery_manager, '_resume_broadcast', new_callable=AsyncMock) as mock_resume:
                    # Set _resume_broadcast to return immediately to avoid warnings
                    mock_resume.return_value = None

                    await recovery_manager.recover_interrupted_broadcasts()

                    mock_cache_manager.get.assert_called_once_with("broadcast:interrupted")
                    mock_resume.assert_called_once_with(broadcast_state)

    @pytest.mark.asyncio
    async def test_recover_interrupted_broadcasts_no_cache(self, recovery_manager):
        """Test recovering broadcasts when no cache available"""
        with patch('bot.misc.recovery.get_cache_manager', return_value=None):
            # Should not raise an exception
            await recovery_manager.recover_interrupted_broadcasts()

    @pytest.mark.asyncio
    async def test_periodic_health_check_success(self, recovery_manager):
        """Test successful health check"""
        # Mock database check
        with patch('bot.misc.recovery.Database') as mock_db:
            mock_session = MagicMock()
            mock_session.execute.return_value = None

            # Mock the context manager for Database().session()
            mock_db_instance = MagicMock()
            mock_db_instance.session.return_value.__enter__.return_value = mock_session
            mock_db_instance.session.return_value.__exit__.return_value = None
            mock_db.return_value = mock_db_instance

            # Mock cache check - ensure all methods return awaitable values
            mock_cache_manager = AsyncMock()
            mock_cache_manager.set = AsyncMock(return_value=True)
            mock_cache_manager.get = AsyncMock(return_value=None)
            with patch('bot.misc.recovery.get_cache_manager', return_value=mock_cache_manager):
                with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
                    with patch('bot.misc.recovery.logger') as mock_logger:
                        with patch('asyncio.sleep') as mock_sleep:  # Prevent actual sleep
                            # Set up counter to exit after first iteration
                            call_count = 0

                            async def mock_sleep_func(seconds):
                                nonlocal call_count
                                call_count += 1
                                if call_count >= 1:
                                    recovery_manager.running = False
                                return None

                            mock_sleep.side_effect = mock_sleep_func
                            recovery_manager.running = True

                            await recovery_manager.periodic_health_check()

                            # Verify database check
                            mock_session.execute.assert_called()

                            # Verify cache check
                            mock_cache_manager.set.assert_called()

                            # Verify bot API check
                            recovery_manager.bot.get_me.assert_called()

                            # Should log success
                            mock_logger.debug.assert_called()

    @pytest.mark.asyncio
    async def test_periodic_health_check_failure(self, recovery_manager):
        """Test health check with failures"""
        # Mock database to fail
        with patch('bot.misc.recovery.Database') as mock_db:
            mock_db_instance = MagicMock()
            mock_db_instance.session.side_effect = Exception("DB Connection failed")
            mock_db.return_value = mock_db_instance

            with patch('bot.misc.recovery.logger') as mock_logger:
                with patch('asyncio.sleep') as mock_sleep:  # Prevent actual sleep
                    # Set up counter to exit after first iteration
                    call_count = 0

                    async def mock_sleep_func(seconds):
                        nonlocal call_count
                        call_count += 1
                        if call_count >= 1:
                            recovery_manager.running = False
                        return None

                    mock_sleep.side_effect = mock_sleep_func
                    recovery_manager.running = True

                    await recovery_manager.periodic_health_check()

                    # Should log the error
                    mock_logger.error.assert_called()


class TestStateManager:
    """Test suite for state manager functionality"""

    @pytest.fixture
    def state_manager(self):
        """Create a StateManager instance"""
        return StateManager()

    def test_state_manager_initialization(self):
        """Test state manager initialization"""
        manager = StateManager()
        assert manager.state_file == "data/bot_state.json"

    @pytest.mark.asyncio
    async def test_save_broadcast_state(self, state_manager):
        """Test saving broadcast state"""
        user_ids = [1, 2, 3, 4, 5]
        sent_count = 3
        message_text = "Test broadcast message"
        start_time = datetime.now()

        mock_cache_manager = AsyncMock()

        with patch('pathlib.Path') as mock_path:
            with patch('builtins.open', mock_open()) as mock_file:
                with patch('bot.misc.recovery.get_cache_manager', return_value=mock_cache_manager):
                    with patch('bot.misc.cache.get_cache_manager', return_value=mock_cache_manager):
                        await state_manager.save_broadcast_state(
                            user_ids, sent_count, message_text, start_time
                        )

                        # Verify directory creation
                        mock_path.assert_called_with("data")
                        mock_path.return_value.mkdir.assert_called_with(exist_ok=True)

                        # Verify file was written
                        mock_file.assert_called_with(state_manager.state_file, 'w')

                        # Verify cache was updated
                        mock_cache_manager.set.assert_called_once()
                        cache_call_args = mock_cache_manager.set.call_args
                        assert cache_call_args[0][0] == "broadcast:state"  # key
                        assert cache_call_args[1]['ttl'] == 3600  # TTL passed as keyword argument

    @pytest.mark.asyncio
    async def test_save_broadcast_state_error_handling(self, state_manager):
        """Test error handling in save_broadcast_state"""
        with patch('builtins.open', side_effect=IOError("File write error")):
            with patch('bot.misc.recovery.logger') as mock_logger:
                await state_manager.save_broadcast_state(
                    [1, 2, 3], 1, "test", datetime.now()
                )

                # Should log the error
                mock_logger.error.assert_called()


class TestMonitoringServer:
    """Test suite for monitoring server functionality"""

    @pytest.fixture
    def monitoring_server(self):
        """Create a MonitoringServer instance"""
        with patch('bot.misc.monitoring.EnvKeys.MONITORING_HOST', '127.0.0.1'):
            with patch('bot.misc.monitoring.EnvKeys.MONITORING_PORT', 8080):
                return MonitoringServer()

    def test_monitoring_server_initialization(self):
        """Test monitoring server initialization"""
        with patch('bot.misc.monitoring.EnvKeys.MONITORING_HOST', '192.168.1.1'):
            with patch('bot.misc.monitoring.EnvKeys.MONITORING_PORT', 9090):
                server = MonitoringServer()
                assert server.host == '192.168.1.1'
                assert server.port == 9090
                assert server.runner is None

    def test_custom_host_port_override(self):
        """Test custom host and port override environment variables"""
        server = MonitoringServer(host='custom.host', port=3000)
        assert server.host == 'custom.host'
        assert server.port == 3000

    @pytest.mark.asyncio
    async def test_health_check_all_healthy(self, monitoring_server):
        """Test health check endpoint when all services are healthy"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {"uptime_seconds": 3600}
        mock_cache_manager = MagicMock()

        with patch('bot.misc.monitoring.Database') as mock_db:
            with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
                with patch('bot.misc.monitoring.get_cache_manager', return_value=mock_cache_manager):
                    # Mock successful database check
                    mock_session = MagicMock()
                    mock_session.execute.return_value = None

                    # Mock the context manager for Database().session()
                    mock_db_instance = MagicMock()
                    mock_db_instance.session.return_value.__enter__.return_value = mock_session
                    mock_db_instance.session.return_value.__exit__.return_value = None
                    mock_db.return_value = mock_db_instance

                    # Create a mock request
                    request = MagicMock()

                    response = await monitoring_server.health_check(request)

                    assert response.status == 200
                    response_data = json.loads(response.text)

                    assert response_data["status"] == "healthy"
                    assert response_data["checks"]["database"] == "ok"
                    assert response_data["checks"]["redis"] == "ok"
                    assert response_data["checks"]["metrics"] == "ok"
                    assert response_data["uptime"] == 3600

    @pytest.mark.asyncio
    async def test_health_check_database_failure(self, monitoring_server):
        """Test health check with database failure"""
        with patch('bot.misc.monitoring.Database') as mock_db:
            with patch('bot.misc.monitoring.get_metrics', return_value=None):
                with patch('bot.misc.monitoring.get_cache_manager', return_value=None):
                    # Mock database failure
                    mock_db_instance = MagicMock()
                    mock_db_instance.session.side_effect = Exception("DB Error")
                    mock_db.return_value = mock_db_instance

                    request = MagicMock()
                    response = await monitoring_server.health_check(request)

                    assert response.status == 503
                    response_data = json.loads(response.text)

                    assert response_data["status"] == "unhealthy"
                    assert "error: DB Error" in response_data["checks"]["database"]
                    assert response_data["checks"]["redis"] == "not configured"

    @pytest.mark.asyncio
    async def test_metrics_json_endpoint(self, monitoring_server):
        """Test metrics JSON endpoint"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "events": {"login": 5, "purchase": 2},
            "uptime_seconds": 1800,
            "timestamp": "2024-01-01T12:00:00"
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.metrics_json(request)

            assert response.status == 200
            assert response.content_type == 'text/html'
            assert 'Metrics JSON' in response.text
            assert '"login": 5' in response.text

    @pytest.mark.asyncio
    async def test_metrics_json_no_metrics(self, monitoring_server):
        """Test metrics JSON endpoint when metrics not initialized"""
        with patch('bot.misc.monitoring.get_metrics', return_value=None):
            request = MagicMock()
            response = await monitoring_server.metrics_json(request)

            assert response.status == 503

    @pytest.mark.asyncio
    async def test_prometheus_handler(self, monitoring_server):
        """Test Prometheus metrics handler"""
        mock_metrics = MagicMock()
        prometheus_data = """
# HELP bot_events_total Total bot events
bot_events_total{event="login"} 5
bot_events_total{event="purchase"} 2
bot_uptime_seconds 1800
        """.strip()
        mock_metrics.export_to_prometheus.return_value = prometheus_data

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.prometheus_handler(request)

            assert response.status == 200
            assert response.content_type == 'text/html'
            assert 'bot_events_total{event="login"} 5' in response.text

    @pytest.mark.asyncio
    async def test_index_handler(self, monitoring_server):
        """Test index/overview handler"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "uptime_seconds": 7200,  # 2 hours
            "events": {"login": 10, "purchase": 5},
            "errors": {"ValueError": 2},
            "timestamp": "2024-01-01T12:00:00"
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.index_handler(request)

            assert response.status == 200
            assert response.content_type == 'text/html'
            assert 'ONLINE' in response.text
            assert '2.0h' in response.text  # 7200/3600 = 2.0 hours
            assert '15' in response.text  # total events: 10 + 5

    @pytest.mark.asyncio
    async def test_events_handler(self, monitoring_server):
        """Test events handler"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "events": {
                "user_login": 100,
                "page_view": 250,
                "purchase": 15
            }
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.events_handler(request)

            assert response.status == 200
            assert 'Event Statistics' in response.text
            assert 'User Login' in response.text
            assert '100' in response.text
            assert '250' in response.text

    @pytest.mark.asyncio
    async def test_performance_handler(self, monitoring_server):
        """Test performance handler"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "timings": {
                "database_query": {
                    "avg": 0.25,
                    "min": 0.1,
                    "max": 0.5,
                    "count": 100
                },
                "api_call": {
                    "avg": 1.2,
                    "min": 0.8,
                    "max": 2.1,
                    "count": 50
                }
            }
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.performance_handler(request)

            assert response.status == 200
            assert 'Performance Metrics' in response.text
            assert 'Database Query' in response.text
            assert '0.250' in response.text  # avg time

    @pytest.mark.asyncio
    async def test_errors_handler_with_errors(self, monitoring_server):
        """Test errors handler with errors present"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "errors": {
                "ValueError": 5,
                "ConnectionError": 12,
                "TimeoutError": 3
            }
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.errors_handler(request)

            assert response.status == 200
            assert 'Error Tracking' in response.text
            assert 'ValueError' in response.text
            assert 'ConnectionError' in response.text

    @pytest.mark.asyncio
    async def test_errors_handler_no_errors(self, monitoring_server):
        """Test errors handler with no errors"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {"errors": {}}

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.errors_handler(request)

            assert response.status == 200
            assert 'No errors detected' in response.text

    @pytest.mark.asyncio
    async def test_dashboard_handler(self, monitoring_server):
        """Test dashboard handler"""
        mock_metrics = MagicMock()
        mock_metrics.get_metrics_summary.return_value = {
            "uptime_seconds": 3661,  # Just over an hour
            "timestamp": "2024-01-01T12:00:00",
            "events": {"login": 50, "logout": 45, "purchase": 10},
            "errors": {"ValueError": 2},
            "conversions": {
                "purchase_funnel": {
                    "view_to_item": 75.0,
                    "item_to_purchase": 25.0
                }
            }
        }

        with patch('bot.misc.monitoring.get_metrics', return_value=mock_metrics):
            request = MagicMock()
            response = await monitoring_server.dashboard_handler(request)

            assert response.status == 200
            assert 'Real-time Dashboard' in response.text
            assert '3661s' in response.text  # uptime
            assert 'login: <strong>50</strong>' in response.text
            assert 'ValueError: <strong>2</strong>' in response.text

    @pytest.mark.asyncio
    async def test_start_server_success(self, monitoring_server):
        """Test successful server startup"""
        with patch('bot.misc.monitoring.web.AppRunner') as mock_runner:
            with patch('bot.misc.monitoring.web.TCPSite') as mock_site:
                with patch('bot.misc.monitoring.logger') as mock_logger:
                    mock_runner_instance = AsyncMock()
                    mock_runner.return_value = mock_runner_instance
                    mock_site_instance = AsyncMock()
                    mock_site.return_value = mock_site_instance

                    await monitoring_server.start()

                    mock_runner.assert_called_once()
                    mock_runner_instance.setup.assert_called_once()
                    mock_site.assert_called_once()
                    mock_site_instance.start.assert_called_once()
                    mock_logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_start_server_failure(self, monitoring_server):
        """Test server startup failure"""
        with patch('bot.misc.monitoring.web.AppRunner', side_effect=Exception("Port in use")):
            with patch('bot.misc.monitoring.logger') as mock_logger:
                await monitoring_server.start()

                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_stop_server(self, monitoring_server):
        """Test server shutdown"""
        mock_runner = AsyncMock()
        monitoring_server.runner = mock_runner

        with patch('bot.misc.monitoring.logger') as mock_logger:
            await monitoring_server.stop()

            mock_runner.cleanup.assert_called_once()
            mock_logger.info.assert_called_with("Monitoring server stopped")

    @pytest.mark.asyncio
    async def test_stop_server_no_runner(self, monitoring_server):
        """Test server shutdown when runner is None"""
        monitoring_server.runner = None

        # Should not raise an exception
        await monitoring_server.stop()

    def test_base_html_generation(self, monitoring_server):
        """Test base HTML generation with navigation"""
        content = "<h1>Test Content</h1>"
        html = monitoring_server._get_base_html("Test Page", content, "dashboard")

        assert "Test Page - Bot Monitoring" in html
        assert content in html
        assert 'class="active"' in html  # Active page should be marked
        assert "Bot Monitoring System" in html
        assert "Auto-refresh every 10 seconds" in html

    def test_route_setup(self, monitoring_server):
        """Test that all routes are properly set up"""
        routes = {route.method + " " + route.resource.canonical: route.handler
                  for route in monitoring_server.app.router.routes()}

        expected_routes = [
            "GET /",
            "GET /health",
            "GET /metrics",
            "GET /metrics/prometheus",
            "GET /dashboard",
            "GET /events",
            "GET /performance",
            "GET /errors"
        ]

        for expected_route in expected_routes:
            assert any(expected_route in route for route in routes.keys())


class TestIntegration:
    """Integration tests for recovery and monitoring systems"""

    @pytest.mark.asyncio
    async def test_recovery_manager_full_cycle(self):
        """Test a complete recovery manager cycle"""
        mock_bot = AsyncMock()
        mock_bot.get_me.return_value = MagicMock(username="testbot")

        # Create payment that needs recovery
        mock_payment = MagicMock()
        mock_payment.id = 1
        mock_payment.provider = "cryptopay"
        mock_payment.external_id = "test_123"
        mock_payment.user_id = 12345
        mock_payment.amount = Decimal("50.00")
        mock_payment.currency = "USD"

        manager = RecoveryManager(mock_bot)

        with patch('bot.misc.recovery.Database') as mock_db:
            with patch('bot.misc.recovery.EnvKeys.CRYPTO_PAY_TOKEN', 'token'):
                with patch('bot.misc.recovery.CryptoPayAPI') as mock_api:
                    with patch('bot.misc.recovery.process_payment_with_referral') as mock_process:
                        with patch('bot.misc.recovery.localize', return_value="Paid"):
                            # Setup mocks
                            mock_session = MagicMock()
                            mock_query = MagicMock()
                            mock_filter = MagicMock()

                            mock_session.query.return_value = mock_query
                            mock_query.filter.return_value = mock_filter
                            mock_filter.all.return_value = [mock_payment]

                            # Mock the context manager for Database().session()
                            mock_db_instance = MagicMock()
                            mock_db_instance.session.return_value.__enter__.return_value = mock_session
                            mock_db_instance.session.return_value.__exit__.return_value = None
                            mock_db.return_value = mock_db_instance

                            mock_api_instance = mock_api.return_value
                            mock_api_instance.get_invoice = AsyncMock(return_value={"status": "paid"})
                            mock_process.return_value = (True, "success")

                            # Set up counter to exit after first iteration
                            manager.running = True

                            # Mock asyncio.sleep to stop after first iteration
                            call_count = 0

                            async def mock_sleep_func(seconds):
                                nonlocal call_count
                                call_count += 1
                                if call_count >= 1:
                                    manager.running = False
                                return None

                            with patch('asyncio.sleep', side_effect=mock_sleep_func):
                                await manager.recover_pending_payments()

                            # Verify the payment was processed
                            mock_api_instance.get_invoice.assert_called_with("test_123")
                            mock_process.assert_called()
                            mock_bot.send_message.assert_called()

    @pytest.mark.asyncio
    async def test_monitoring_server_with_real_metrics(self):
        """Test monitoring server with actual metrics data"""
        from bot.misc.metrics import MetricsCollector

        # Create real metrics
        metrics = MetricsCollector()
        metrics.track_event("login", 123)
        metrics.track_event("purchase", 124)
        metrics.track_timing("db_query", 0.5)
        metrics.track_error("ValueError")

        server = MonitoringServer('127.0.0.1', 8080)

        with patch('bot.misc.monitoring.get_metrics', return_value=metrics):
            request = MagicMock()

            # Test multiple endpoints
            response = await server.index_handler(request)
            assert response.status == 200
            assert "2" in response.text  # Total events

            response = await server.events_handler(request)
            assert response.status == 200
            assert "login" in response.text.lower()

            response = await server.performance_handler(request)
            assert response.status == 200

            response = await server.errors_handler(request)
            assert response.status == 200
            assert "ValueError" in response.text
