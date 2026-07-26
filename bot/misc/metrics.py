import re
import time
from datetime import datetime
from typing import Dict, Any, Optional, List
from collections import defaultdict

from bot.logger_mesh import logger

# A Prometheus label value must not carry a raw quote, backslash or newline — event names are derived from user-supplied callback_data,
# so anything else would let a crafted payload forge extra metric lines.
_PROM_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')


def _prom_label(value: str) -> str:
    """Return a label value safe to interpolate into the exposition format."""
    cleaned = str(value).replace("-", "_").replace("/", "_").replace(" ", "_")
    return cleaned if _PROM_NAME_RE.match(cleaned) else "other"


class MetricsCollector:
    """Metrics builder for analytics"""

    MAX_CONVERSION_USERS = 50_000
    # Event/timing names partly derive from user-supplied callback_data, so the
    # key space is attacker-influenced. Cap the distinct series a collector will
    # hold; everything past the cap folds into OVERFLOW_KEY.
    MAX_SERIES = 500
    OVERFLOW_KEY = "other"

    def __init__(self):
        # Initializing all attributes
        self.events: Dict[str, int] = defaultdict(int)
        self.timings: Dict[str, List[float]] = defaultdict(list)
        self.errors: Dict[str, int] = defaultdict(int)
        self.conversions: Dict[str, Dict] = {}
        self.start_time = datetime.now()
        self.last_flush = datetime.now()

    def _bounded_key(self, store: Dict[str, Any], key: str) -> str:
        """Return `key`, or OVERFLOW_KEY once `store` is at its series cap."""
        if key in store or len(store) < self.MAX_SERIES:
            return key
        return self.OVERFLOW_KEY

    def track_event(self, event_name: str, user_id: Optional[int] = None,
                    metadata: Optional[Dict] = None):
        """Event Tracking"""
        self.events[self._bounded_key(self.events, event_name)] += 1

    def track_timing(self, operation: str, duration: float):
        """Tracking the time of an operation"""
        operation = self._bounded_key(self.timings, operation)
        self.timings[operation].append(duration)

        # Hold only the last 1000 measurements
        if len(self.timings[operation]) > 1000:
            self.timings[operation] = self.timings[operation][-1000:]

    def track_error(self, error_type: str, error_msg: str = None):
        """Error Tracking"""
        self.errors[self._bounded_key(self.errors, error_type)] += 1

        if error_msg:
            logger.error(f"Metric error [{error_type}]: {error_msg}")

    def track_conversion(self, funnel: str, step: str, user_id: int):
        """Tracking conversions in the funnel"""
        if funnel not in self.conversions:
            self.conversions[funnel] = defaultdict(set)

        bucket = self.conversions[funnel][step]
        # Bound memory: stop growing once the cap is hit. Prevents an unbounded per-user set over long uptimes.
        if user_id in bucket or len(bucket) < self.MAX_CONVERSION_USERS:
            bucket.add(user_id)

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

    def export_to_prometheus(self):
        """Exporting metrics in Prometheus format"""
        lines = []

        # Events
        for event, count in self.events.items():
            lines.append(f'bot_events_total{{event="{_prom_label(event)}"}} {count}')

        # Errors
        for error, count in self.errors.items():
            lines.append(f'bot_errors_total{{type="{_prom_label(error)}"}} {count}')

        # Timers
        for op, times in self.timings.items():
            if times:
                avg_time = sum(times) / len(times)
                lines.append(
                    f'bot_operation_duration_seconds{{operation="{_prom_label(op)}"}} {avg_time}'
                )

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

        try:
            # Try to access text attribute to see if it exists and has a value
            text_value = getattr(event, 'text', None)
            if text_value is not None and text_value != "":
                event_type = "message"
                if text_value and text_value.startswith('/'):
                    event_type = f"command_{_prom_label(text_value.split()[0][1:])}"
            elif hasattr(event, 'data'):  # CallbackQuery (including data=None)
                event_type = _prom_label(event.data.split('_')[0]) if event.data else "unknown"
        except AttributeError:
            # If we can't access text (deleted attribute), check for data
            if hasattr(event, 'data'):
                event_type = _prom_label(event.data.split('_')[0]) if event.data else "unknown"

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
