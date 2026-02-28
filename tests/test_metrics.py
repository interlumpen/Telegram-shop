import pytest
from unittest.mock import AsyncMock, MagicMock

from bot.misc.metrics import MetricsCollector, AnalyticsMiddleware


class TestMetricsCollector:

    def setup_method(self):
        self.m = MetricsCollector()

    def test_track_event(self):
        self.m.track_event("page_view")
        self.m.track_event("page_view")
        assert self.m.events["page_view"] == 2

    def test_track_timing(self):
        self.m.track_timing("handler_shop", 0.15)
        self.m.track_timing("handler_shop", 0.25)
        assert len(self.m.timings["handler_shop"]) == 2

    def test_track_timing_limits_to_1000(self):
        for i in range(1100):
            self.m.track_timing("op", float(i))
        assert len(self.m.timings["op"]) == 1000

    def test_track_error(self):
        self.m.track_error("ValueError")
        self.m.track_error("ValueError")
        self.m.track_error("TypeError")
        assert self.m.errors["ValueError"] == 2
        assert self.m.errors["TypeError"] == 1

    def test_track_conversion(self):
        self.m.track_conversion("purchase_funnel", "view_shop", 1)
        self.m.track_conversion("purchase_funnel", "view_shop", 2)
        self.m.track_conversion("purchase_funnel", "view_item", 1)
        self.m.track_conversion("purchase_funnel", "purchase", 1)
        assert len(self.m.conversions["purchase_funnel"]["view_shop"]) == 2
        assert len(self.m.conversions["purchase_funnel"]["purchase"]) == 1

    def test_get_metrics_summary(self):
        self.m.track_event("test_event")
        self.m.track_timing("test_op", 0.5)
        summary = self.m.get_metrics_summary()
        assert "uptime_seconds" in summary
        assert "events" in summary
        assert "timings" in summary
        assert "errors" in summary
        assert summary["events"]["test_event"] == 1
        assert summary["timings"]["test_op"]["avg"] == 0.5

    def test_conversion_rates_calculation(self):
        self.m.track_conversion("purchase_funnel", "view_shop", 1)
        self.m.track_conversion("purchase_funnel", "view_shop", 2)
        self.m.track_conversion("purchase_funnel", "view_shop", 3)
        self.m.track_conversion("purchase_funnel", "view_shop", 4)
        self.m.track_conversion("purchase_funnel", "view_item", 1)
        self.m.track_conversion("purchase_funnel", "view_item", 2)
        self.m.track_conversion("purchase_funnel", "purchase", 1)

        summary = self.m.get_metrics_summary()
        rates = summary["conversions"]["purchase_funnel"]
        assert rates["view_to_item"] == 50.0  # 2/4
        assert rates["item_to_purchase"] == 50.0  # 1/2
        assert rates["total"] == 25.0  # 1/4

    def test_export_prometheus_format(self):
        self.m.track_event("test_event")
        self.m.track_error("TestError")
        self.m.track_timing("test_op", 0.1)
        output = self.m.export_to_prometheus()
        assert 'bot_events_total{event="test_event"} 1' in output
        assert 'bot_errors_total{type="TestError"} 1' in output
        assert 'bot_operation_duration_seconds{operation="test_op"}' in output
        assert "bot_uptime_seconds" in output

    def test_export_prometheus_cleans_names(self):
        self.m.track_event("my-event/test case")
        output = self.m.export_to_prometheus()
        assert "my_event_test_case" in output


class TestAnalyticsMiddleware:

    def setup_method(self):
        self.metrics = MetricsCollector()
        self.mw = AnalyticsMiddleware(self.metrics)

    @pytest.mark.asyncio
    async def test_tracks_message_event(self):
        event = MagicMock()
        event.from_user = MagicMock()
        event.from_user.id = 123
        event.text = "hello"
        # Remove data attribute so it's treated as message
        del event.data

        handler = AsyncMock(return_value=None)
        await self.mw(handler, event, {})

        assert self.metrics.events.get("bot_message", 0) == 1
        handler.assert_called_once()

    @pytest.mark.asyncio
    async def test_tracks_command_event(self):
        event = MagicMock()
        event.from_user = MagicMock()
        event.from_user.id = 123
        event.text = "/start 12345"
        del event.data

        handler = AsyncMock(return_value=None)
        await self.mw(handler, event, {})

        assert self.metrics.events.get("bot_command_start", 0) == 1

    @pytest.mark.asyncio
    async def test_tracks_callback_event(self):
        event = MagicMock()
        event.from_user = MagicMock()
        event.from_user.id = 123
        event.text = None
        event.data = "shop_view"

        handler = AsyncMock(return_value=None)
        await self.mw(handler, event, {})

        assert self.metrics.events.get("bot_shop", 0) == 1

    @pytest.mark.asyncio
    async def test_tracks_error(self):
        event = MagicMock()
        event.from_user = MagicMock()
        event.from_user.id = 123
        event.text = "test"
        del event.data

        handler = AsyncMock(side_effect=ValueError("test error"))

        with pytest.raises(ValueError):
            await self.mw(handler, event, {})

        assert self.metrics.errors["ValueError"] == 1

    @pytest.mark.asyncio
    async def test_tracks_timing(self):
        event = MagicMock()
        event.from_user = MagicMock()
        event.from_user.id = 123
        event.text = "test"
        del event.data

        handler = AsyncMock(return_value=None)
        await self.mw(handler, event, {})

        assert len(self.metrics.timings["handler_message"]) == 1
