import asyncio

import pytest
import time
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch
from collections import defaultdict

from bot.misc.metrics import MetricsCollector, AnalyticsMiddleware, get_metrics, init_metrics


class TestMetricsCollector:
    """Test suite for metrics collector functionality"""

    def test_metrics_collector_initialization(self):
        """Test metrics collector initialization"""
        collector = MetricsCollector()

        assert isinstance(collector.events, dict)
        assert isinstance(collector.timings, dict)
        assert isinstance(collector.errors, dict)
        assert isinstance(collector.conversions, dict)
        assert isinstance(collector.start_time, datetime)
        assert isinstance(collector.last_flush, datetime)

        # Should be empty initially
        assert len(collector.events) == 0
        assert len(collector.timings) == 0
        assert len(collector.errors) == 0
        assert len(collector.conversions) == 0

    def test_track_event_simple(self):
        """Test simple event tracking"""
        collector = MetricsCollector()

        collector.track_event("user_click")
        collector.track_event("user_click")
        collector.track_event("page_view")

        assert collector.events["user_click"] == 2
        assert collector.events["page_view"] == 1

    def test_track_event_with_metadata(self):
        """Test event tracking with metadata"""
        collector = MetricsCollector()

        # Mock the _save_event method to verify it's called
        with patch.object(collector, '_save_event') as mock_save_event:
            collector.track_event(
                "purchase",
                user_id=12345,
                metadata={"amount": 100, "currency": "USD"}
            )

            assert collector.events["purchase"] == 1
            mock_save_event.assert_called_once()

            # Check the saved event data
            call_args = mock_save_event.call_args
            event_name = call_args[0][0]
            event_data = call_args[0][1]

            assert event_name == "purchase"
            assert event_data["user_id"] == 12345
            assert event_data["metadata"]["amount"] == 100
            assert "timestamp" in event_data

    def test_track_timing(self):
        """Test timing tracking"""
        collector = MetricsCollector()

        collector.track_timing("database_query", 0.5)
        collector.track_timing("database_query", 0.3)
        collector.track_timing("api_call", 1.2)

        assert len(collector.timings["database_query"]) == 2
        assert collector.timings["database_query"] == [0.5, 0.3]
        assert collector.timings["api_call"] == [1.2]

    def test_track_timing_limit(self):
        """Test timing storage limit"""
        collector = MetricsCollector()

        # Add 1005 measurements
        for i in range(1005):
            collector.track_timing("test_operation", float(i))

        # Should keep only the last 1000
        assert len(collector.timings["test_operation"]) == 1000
        assert collector.timings["test_operation"][0] == 5.0  # Should start from 5
        assert collector.timings["test_operation"][-1] == 1004.0  # Should end at 1004

    def test_track_error(self):
        """Test error tracking"""
        collector = MetricsCollector()

        with patch('bot.misc.metrics.logger') as mock_logger:
            collector.track_error("ValueError")
            collector.track_error("ValueError")
            collector.track_error("ConnectionError", "Database connection failed")

            assert collector.errors["ValueError"] == 2
            assert collector.errors["ConnectionError"] == 1

            # Should log detailed error message
            mock_logger.error.assert_called_with(
                "Metric error [ConnectionError]: Database connection failed"
            )

    def test_track_conversion(self):
        """Test conversion funnel tracking"""
        collector = MetricsCollector()

        # Track users through purchase funnel
        collector.track_conversion("purchase_funnel", "view_shop", 1001)
        collector.track_conversion("purchase_funnel", "view_shop", 1002)
        collector.track_conversion("purchase_funnel", "view_item", 1001)
        collector.track_conversion("purchase_funnel", "purchase", 1001)

        funnel = collector.conversions["purchase_funnel"]
        assert 1001 in funnel["view_shop"]
        assert 1002 in funnel["view_shop"]
        assert 1001 in funnel["view_item"]
        assert 1002 not in funnel["view_item"]
        assert 1001 in funnel["purchase"]

    def test_get_metrics_summary(self):
        """Test metrics summary generation"""
        collector = MetricsCollector()

        # Add some test data
        collector.track_event("login", 123)
        collector.track_event("purchase", 124)
        collector.track_timing("db_query", 0.5)
        collector.track_timing("db_query", 0.3)
        collector.track_error("ValueError")

        # Track conversions
        collector.track_conversion("purchase_funnel", "view_shop", 123)
        collector.track_conversion("purchase_funnel", "view_item", 123)
        collector.track_conversion("purchase_funnel", "purchase", 123)

        summary = collector.get_metrics_summary()

        # Check basic structure
        assert "uptime_seconds" in summary
        assert "events" in summary
        assert "timings" in summary
        assert "errors" in summary
        assert "conversions" in summary
        assert "timestamp" in summary

        # Check events
        assert summary["events"]["login"] == 1
        assert summary["events"]["purchase"] == 1

        # Check timings
        assert "db_query" in summary["timings"]
        timing_stats = summary["timings"]["db_query"]
        assert timing_stats["avg"] == 0.4  # (0.5 + 0.3) / 2
        assert timing_stats["min"] == 0.3
        assert timing_stats["max"] == 0.5
        assert timing_stats["count"] == 2

        # Check errors
        assert summary["errors"]["ValueError"] == 1

        # Check conversions
        conversions = summary["conversions"]["purchase_funnel"]
        assert conversions["view_to_item"] == 100.0  # 1/1 * 100
        assert conversions["item_to_purchase"] == 100.0  # 1/1 * 100
        assert conversions["total"] == 100.0  # 1/1 * 100

    def test_conversion_rates_calculation(self):
        """Test conversion rate calculations with realistic data"""
        collector = MetricsCollector()

        # 100 users view shop
        for user_id in range(1, 101):
            collector.track_conversion("purchase_funnel", "view_shop", user_id)

        # 30 users view items
        for user_id in range(1, 31):
            collector.track_conversion("purchase_funnel", "view_item", user_id)

        # 5 users make purchases
        for user_id in range(1, 6):
            collector.track_conversion("purchase_funnel", "purchase", user_id)

        summary = collector.get_metrics_summary()
        conversions = summary["conversions"]["purchase_funnel"]

        assert conversions["view_to_item"] == 30.0  # 30/100 * 100
        assert conversions["item_to_purchase"] == pytest.approx(16.67, abs=0.1)  # 5/30 * 100
        assert conversions["total"] == 5.0  # 5/100 * 100

    def test_empty_conversions(self):
        """Test conversion calculations with empty data"""
        collector = MetricsCollector()

        summary = collector.get_metrics_summary()

        # Should not crash on empty data
        assert "conversions" in summary
        assert summary["conversions"] == {}

    @pytest.mark.asyncio
    async def test_export_to_prometheus(self):
        """Test Prometheus metrics export"""
        collector = MetricsCollector()

        # Add test data
        collector.track_event("user-login")  # Test special character handling
        collector.track_event("page/view")  # Test slash handling
        collector.track_event("button click")  # Test space handling
        collector.track_timing("database-query", 0.5)
        collector.track_error("Connection/Error")

        prometheus_output = collector.export_to_prometheus()

        # Check that metrics are properly formatted
        lines = prometheus_output.split('\n')

        # Find specific metrics
        event_metrics = [line for line in lines if line.startswith('bot_events_total')]
        error_metrics = [line for line in lines if line.startswith('bot_errors_total')]
        timing_metrics = [line for line in lines if line.startswith('bot_operation_duration_seconds')]
        uptime_metrics = [line for line in lines if line.startswith('bot_uptime_seconds')]

        # Check event metrics with sanitized names
        assert any('event="user_login"' in line for line in event_metrics)
        assert any('event="page_view"' in line for line in event_metrics)
        assert any('event="button_click"' in line for line in event_metrics)

        # Check error metrics
        assert any('type="Connection_Error"' in line for line in error_metrics)

        # Check timing metrics
        assert any('operation="database_query"' in line for line in timing_metrics)

        # Check uptime metric
        assert len(uptime_metrics) == 1
        assert 'bot_uptime_seconds' in uptime_metrics[0]

    def test_save_event_logging(self):
        """Test event saving with logging"""
        collector = MetricsCollector()

        with patch('bot.misc.metrics.logger') as mock_logger:
            event_data = {"user_id": 123, "amount": 100}
            collector._save_event("test_event", event_data)

            mock_logger.debug.assert_called_once()
            log_call = mock_logger.debug.call_args[0][0]
            assert "Analytics event: test_event" in log_call

    def test_save_event_error_handling(self):
        """Test error handling in event saving"""
        collector = MetricsCollector()

        with patch('bot.misc.metrics.logger') as mock_logger:
            # Mock logger.debug to raise an exception
            mock_logger.debug.side_effect = Exception("Logging error")

            collector._save_event("test_event", {"data": "test"})

            # Should log the error
            mock_logger.error.assert_called()


class TestAnalyticsMiddleware:
    """Test suite for analytics middleware"""

    def test_analytics_middleware_initialization(self):
        """Test analytics middleware initialization"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        assert middleware.metrics == metrics

    @pytest.mark.asyncio
    async def test_middleware_message_handling(self):
        """Test middleware handling of messages"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        # Mock message event
        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.text = "Hello bot"

        # Mock handler
        handler = AsyncMock(return_value="response")

        result = await middleware(handler, message, {})

        assert result == "response"
        handler.assert_called_once_with(message, {})

        # Check that message event was tracked
        assert metrics.events["bot_message"] == 1

        # Check timing was recorded
        assert "handler_message" in metrics.timings
        assert len(metrics.timings["handler_message"]) == 1

    @pytest.mark.asyncio
    async def test_middleware_command_handling(self):
        """Test middleware handling of commands"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        # Mock command message
        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.text = "/start some params"

        handler = AsyncMock(return_value="response")

        await middleware(handler, message, {})

        # Should track as command_start
        assert metrics.events["bot_command_start"] == 1
        assert "handler_command_start" in metrics.timings

    @pytest.mark.asyncio
    async def test_middleware_callback_query_handling(self):
        """Test middleware handling of callback queries"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        # Mock callback query
        callback = MagicMock()
        callback.from_user = MagicMock()
        callback.from_user.id = 12345
        callback.data = "shop_category_1"
        # Remove text attribute to simulate callback query
        del callback.text

        handler = AsyncMock(return_value="response")

        await middleware(handler, callback, {})

        # Should track as shop event (first part of callback data)
        assert metrics.events["bot_shop"] == 1
        assert "handler_shop" in metrics.timings

    @pytest.mark.asyncio
    async def test_middleware_callback_query_no_data(self):
        """Test middleware handling of callback queries without data"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        # Mock callback query without data
        callback = MagicMock()
        callback.from_user = MagicMock()
        callback.from_user.id = 12345
        callback.data = None
        del callback.text

        handler = AsyncMock(return_value="response")

        await middleware(handler, callback, {})

        # Should track as unknown event
        assert metrics.events["bot_unknown"] == 1

    @pytest.mark.asyncio
    async def test_middleware_error_tracking(self):
        """Test middleware error tracking"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.text = "test"

        # Handler that raises an exception
        handler = AsyncMock(side_effect=ValueError("Test error"))

        with pytest.raises(ValueError, match="Test error"):
            await middleware(handler, message, {})

        # Should track the error
        assert metrics.errors["ValueError"] == 1

    @pytest.mark.asyncio
    async def test_middleware_timing_accuracy(self):
        """Test that middleware timing is reasonably accurate"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        message = MagicMock()
        message.from_user = MagicMock()
        message.from_user.id = 12345
        message.text = "test"

        # Handler that takes some time
        async def slow_handler(event, data):
            await asyncio.sleep(0.1)  # 100ms delay
            return "response"

        start_time = time.time()
        await middleware(slow_handler, message, {})
        actual_duration = time.time() - start_time

        # Check recorded timing
        recorded_timing = metrics.timings["handler_message"][0]

        # Should be close to actual duration (within 50ms tolerance)
        assert abs(recorded_timing - actual_duration) < 0.05

    @pytest.mark.asyncio
    async def test_middleware_event_without_user(self):
        """Test middleware handling events without user information"""
        metrics = MetricsCollector()
        middleware = AnalyticsMiddleware(metrics)

        # Event without from_user
        event = MagicMock()
        event.text = "test"
        del event.from_user

        handler = AsyncMock(return_value="response")

        result = await middleware(handler, event, {})

        assert result == "response"
        # Should still track the event
        assert metrics.events["bot_message"] == 1


class TestMetricsGlobal:
    """Test suite for global metrics functions"""

    def test_get_metrics_initially_none(self):
        """Test that global metrics is initially None"""
        with patch('bot.misc.metrics._metrics_collector', None):
            metrics = get_metrics()
            assert metrics is None

    def test_init_metrics(self):
        """Test metrics initialization"""
        with patch('bot.misc.metrics.logger') as mock_logger:
            metrics = init_metrics()

            assert isinstance(metrics, MetricsCollector)
            assert get_metrics() == metrics
            mock_logger.info.assert_called_with("Metrics collector initialized")

    def test_metrics_persistence(self):
        """Test that metrics persist after initialization"""
        metrics1 = init_metrics()
        metrics2 = get_metrics()

        assert metrics1 is metrics2


class TestMetricsIntegration:
    """Integration tests for metrics functionality"""

    @pytest.mark.asyncio
    async def test_complete_user_journey_tracking(self):
        """Test tracking a complete user journey"""
        collector = MetricsCollector()

        user_id = 12345

        # User views shop
        collector.track_event("shop_view", user_id)
        collector.track_conversion("purchase_funnel", "view_shop", user_id)

        # User searches (with timing)
        collector.track_timing("search_query", 0.2)
        collector.track_event("search", user_id, {"query": "laptop"})

        # User views item
        collector.track_event("item_view", user_id)
        collector.track_conversion("purchase_funnel", "view_item", user_id)

        # User makes purchase
        collector.track_event("purchase", user_id, {
            "item_id": "laptop_123",
            "amount": 999.99,
            "currency": "USD"
        })
        collector.track_conversion("purchase_funnel", "purchase", user_id)
        collector.track_timing("payment_processing", 1.5)

        # Generate summary
        summary = collector.get_metrics_summary()

        # Verify all events were tracked
        assert summary["events"]["shop_view"] == 1
        assert summary["events"]["search"] == 1
        assert summary["events"]["item_view"] == 1
        assert summary["events"]["purchase"] == 1

        # Verify timings
        assert "search_query" in summary["timings"]
        assert "payment_processing" in summary["timings"]

        # Verify perfect conversion (same user throughout)
        conversions = summary["conversions"]["purchase_funnel"]
        assert conversions["total"] == 100.0  # 1/1 * 100

    def test_metrics_with_special_characters(self):
        """Test metrics handling with special characters and edge cases"""
        collector = MetricsCollector()

        # Test various event names with special characters
        collector.track_event("user-action/click")
        collector.track_event("page view with spaces")
        collector.track_event("event.with.dots")
        collector.track_event("пользователь_действие")  # Cyrillic
        collector.track_event("用户操作")  # Chinese

        # All events should be tracked
        assert len(collector.events) == 5

        # Test error with special characters
        collector.track_error("Custom/Error-Type")
        assert collector.errors["Custom/Error-Type"] == 1

        # Should not crash when generating summary
        summary = collector.get_metrics_summary()
        assert len(summary["events"]) == 5
