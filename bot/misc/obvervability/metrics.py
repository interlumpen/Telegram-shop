import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import defaultdict

from bot.logger_mesh import logger


class MetricsCollector:
    """Metrics builder for analytics"""

    def __init__(self):
        # Initializing all attributes
        self.events: Dict[str, int] = defaultdict(int)
        self.timings: Dict[str, List[float]] = defaultdict(list)
        self.errors: Dict[str, int] = defaultdict(int)
        self.conversions: Dict[str, Dict] = {}
        self.start_time = datetime.now()
        self.last_flush = datetime.now()

    def track_event(self, event_name: str, user_id: Optional[int] = None,
                    metadata: Optional[Dict] = None):
        """Event Tracking"""
        self.events[event_name] += 1

        # Saving detailed information for important events
        if event_name in ["purchase", "payment", "registration"]:
            event_data = {
                "timestamp": datetime.now().isoformat(),
                "user_id": user_id,
                "metadata": metadata
            }
            self._save_event(event_name, event_data)

    def track_timing(self, operation: str, duration: float):
        """Tracking the time of an operation"""
        self.timings[operation].append(duration)

        # Hold only the last 1000 measurements
        if len(self.timings[operation]) > 1000:
            self.timings[operation] = self.timings[operation][-1000:]

    def track_error(self, error_type: str, error_msg: str = None):
        """Error Tracking"""
        self.errors[error_type] += 1

        if error_msg:
            logger.error(f"Metric error [{error_type}]: {error_msg}")

    def track_conversion(self, funnel: str, step: str, user_id: int):
        """Tracking conversions in the funnel"""
        if funnel not in self.conversions:
            self.conversions[funnel] = defaultdict(set)

        self.conversions[funnel][step].add(user_id)

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Getting a metrics summary"""
        uptime = (datetime.now() - self.start_time).total_seconds()

        # Calculation of average times
        avg_timings = {}
        for op, times in self.timings.items():
            if times:
                avg_timings[op] = {
                    "avg": sum(times) / len(times),
                    "min": min(times),
                    "max": max(times),
                    "count": len(times)
                }

        # Conversion calculation
        conversion_rates = {}
        for funnel, steps in self.conversions.items():
            if funnel == "purchase_funnel":
                view_shop = len(steps.get("view_shop", set()))
                view_item = len(steps.get("view_item", set()))
                purchase = len(steps.get("purchase", set()))

                conversion_rates[funnel] = {
                    "view_to_item": (view_item / view_shop * 100) if view_shop else 0,
                    "item_to_purchase": (purchase / view_item * 100) if view_item else 0,
                    "total": (purchase / view_shop * 100) if view_shop else 0
                }

        return {
            "uptime_seconds": uptime,
            "events": dict(self.events),
            "timings": avg_timings,
            "errors": dict(self.errors),
            "conversions": conversion_rates,
            "timestamp": datetime.now().isoformat()
        }

    def _save_event(self, event_name: str, event_data: Dict):
        """Saving the event for further analysis"""
        try:
            logger.debug(f"Analytics event: {event_name} - {event_data}")
        except Exception as e:
            logger.error(f"Failed to save event to DB: {e}")

    def export_to_prometheus(self):
        """Exporting metrics in Prometheus format"""
        lines = []

        # Events
        for event, count in self.events.items():
            # Clearing the event name for Prometheus (replacing invalid characters)
            clean_event = event.replace("-", "_").replace("/", "_").replace(" ", "_")
            lines.append(f'bot_events_total{{event="{clean_event}"}} {count}')

        # Errors
        for error, count in self.errors.items():
            clean_error = error.replace("-", "_").replace("/", "_").replace(" ", "_")
            lines.append(f'bot_errors_total{{type="{clean_error}"}} {count}')

        # Timers
        for op, times in self.timings.items():
            if times:
                avg_time = sum(times) / len(times)
                clean_op = op.replace("-", "_").replace("/", "_").replace(" ", "_")
                lines.append(f'bot_operation_duration_seconds{{operation="{clean_op}"}} {avg_time}')

        # Add uptime
        uptime = (datetime.now() - self.start_time).total_seconds()
        lines.append(f'bot_uptime_seconds {uptime}')

        return "\n".join(lines)


class AnalyticsMiddleware:
    """Middleware for analytics collection"""

    def __init__(self, metrics: MetricsCollector):
        self.metrics = metrics

    async def __call__(self, handler, event, data):
        start_time = time.time()

        # Retrieve event information
        user_id = None
        event_type = None

        try:
            if hasattr(event, 'from_user') and event.from_user:
                user_id = event.from_user.id
        except AttributeError:
            # from_user may not exist or may be deleted
            pass

        # Determine event type - check attributes but handle test mocks properly
        try:
            # Try to access text attribute to see if it exists and has a value
            text_value = getattr(event, 'text', None)
            if text_value is not None and text_value != "":
                event_type = "message"
                if text_value and text_value.startswith('/'):
                    event_type = f"command_{text_value.split()[0][1:]}"
            elif hasattr(event, 'data'):  # CallbackQuery (including data=None)
                event_type = event.data.split('_')[0] if event.data else "unknown"
        except AttributeError:
            # If we can't access text (deleted attribute), check for data
            if hasattr(event, 'data'):
                event_type = event.data.split('_')[0] if event.data else "unknown"

        # Event Tracking
        if event_type:
            self.metrics.track_event(f"bot_{event_type}", user_id)

        try:
            result = await handler(event, data)

            # Run time tracking
            duration = time.time() - start_time
            if event_type:
                self.metrics.track_timing(f"handler_{event_type}", duration)

            return result

        except Exception as e:
            # Tracking errors
            self.metrics.track_error(type(e).__name__, str(e))
            raise


# Global instance of metrics
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics() -> Optional[MetricsCollector]:
    """Getting a global metrics collector"""
    return _metrics_collector


def init_metrics() -> MetricsCollector:
    """Initialization of the metrics collector"""
    global _metrics_collector
    _metrics_collector = MetricsCollector()
    logger.info("Metrics collector initialized")
    return _metrics_collector
