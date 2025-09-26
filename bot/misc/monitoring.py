from aiohttp import web
import json

from bot.misc import EnvKeys
from bot.misc.metrics import get_metrics
from bot.database import Database
from bot.misc.cache import get_cache_manager
from bot.logger_mesh import logger


class MonitoringServer:
    """monitoring server with UI"""

    def __init__(self, host: str = None, port: int = None):
        self.host = host or EnvKeys.MONITORING_HOST
        self.port = port or EnvKeys.MONITORING_PORT
        self.app = web.Application()
        self.runner = None
        self._setup_routes()

    def _setup_routes(self):
        """Setup routes"""
        self.app.router.add_get('/health', self.health_check)
        self.app.router.add_get('/metrics', self.metrics_json)
        self.app.router.add_get('/metrics/prometheus', self.prometheus_handler)
        self.app.router.add_get('/dashboard', self.dashboard_handler)
        self.app.router.add_get('/events', self.events_handler)
        self.app.router.add_get('/performance', self.performance_handler)
        self.app.router.add_get('/errors', self.errors_handler)
        self.app.router.add_get('/', self.index_handler)

    def _get_base_html(self, title: str, content: str, active_page: str = "") -> str:
        """Generate base HTML with navigation"""
        nav_items = [
            ('/', 'Overview', 'overview'),
            ('/dashboard', 'Dashboard', 'dashboard'),
            ('/events', 'Events', 'events'),
            ('/performance', 'Performance', 'performance'),
            ('/errors', 'Errors', 'errors'),
            ('/metrics', 'Raw JSON', 'json'),
            ('/metrics/prometheus', 'Prometheus', 'prometheus'),
        ]

        nav_html = ""
        for url, label, page_id in nav_items:
            active_class = "active" if page_id == active_page else ""
            nav_html += f'<a href="{url}" class="{active_class}">{label}</a>'

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>{title} - Bot Monitoring</title>
            <meta http-equiv="refresh" content="10">
            <style>
                * {{ margin: 0; padding: 0; box-sizing: border-box; }}
                body {{ 
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    padding: 20px;
                }}
                .container {{
                    max-width: 1200px;
                    margin: 0 auto;
                    background: rgba(255, 255, 255, 0.95);
                    border-radius: 20px;
                    box-shadow: 0 20px 60px rgba(0,0,0,0.3);
                    overflow: hidden;
                }}
                .header {{
                    background: linear-gradient(135deg, #6B73FF 0%, #000DFF 100%);
                    color: white;
                    padding: 30px;
                    text-align: center;
                }}
                h1 {{ 
                    font-size: 2.5em;
                    margin-bottom: 10px;
                    text-shadow: 2px 2px 4px rgba(0,0,0,0.2);
                }}
                .nav {{
                    display: flex;
                    justify-content: center;
                    background: rgba(0,0,0,0.1);
                    padding: 0;
                    flex-wrap: wrap;
                }}
                .nav a {{
                    color: white;
                    text-decoration: none;
                    padding: 15px 20px;
                    transition: all 0.3s;
                    position: relative;
                }}
                .nav a:hover {{
                    background: rgba(255,255,255,0.1);
                }}
                .nav a.active {{
                    background: rgba(255,255,255,0.2);
                }}
                .nav a.active::after {{
                    content: '';
                    position: absolute;
                    bottom: 0;
                    left: 0;
                    right: 0;
                    height: 3px;
                    background: white;
                }}
                .content {{
                    padding: 30px;
                }}
                .metric-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                    gap: 20px;
                    margin-bottom: 30px;
                }}
                .metric-card {{
                    background: white;
                    padding: 25px;
                    border-radius: 15px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                    transition: transform 0.3s, box-shadow 0.3s;
                }}
                .metric-card:hover {{
                    transform: translateY(-5px);
                    box-shadow: 0 10px 25px rgba(0,0,0,0.15);
                }}
                .metric-value {{
                    font-size: 2.5em;
                    font-weight: bold;
                    color: #6B73FF;
                    margin: 10px 0;
                }}
                .metric-label {{
                    color: #666;
                    font-size: 0.9em;
                    text-transform: uppercase;
                    letter-spacing: 1px;
                }}
                .chart {{
                    background: white;
                    padding: 25px;
                    border-radius: 15px;
                    box-shadow: 0 5px 15px rgba(0,0,0,0.1);
                    margin-bottom: 20px;
                }}
                .status-ok {{ color: #4CAF50; }}
                .status-warning {{ color: #FF9800; }}
                .status-error {{ color: #f44336; }}
                .progress-bar {{
                    width: 100%;
                    height: 30px;
                    background: #e0e0e0;
                    border-radius: 15px;
                    overflow: hidden;
                    margin-top: 10px;
                }}
                .progress-fill {{
                    height: 100%;
                    background: linear-gradient(90deg, #4CAF50, #8BC34A);
                    transition: width 0.5s;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                    font-weight: bold;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    margin-top: 20px;
                    background: white;
                    border-radius: 10px;
                    overflow: hidden;
                }}
                th {{
                    background: #6B73FF;
                    color: white;
                    padding: 15px;
                    text-align: left;
                }}
                td {{
                    padding: 12px 15px;
                    border-bottom: 1px solid #e0e0e0;
                }}
                tr:hover {{
                    background: #f5f5f5;
                }}
                .footer {{
                    text-align: center;
                    padding: 20px;
                    color: #666;
                    background: #f5f5f5;
                }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🤖 Bot Monitoring System</h1>
                    <div class="nav">{nav_html}</div>
                </div>
                <div class="content">
                    {content}
                </div>
                <div class="footer">
                    <p>Auto-refresh every 10 seconds | Bot Monitoring v1.0</p>
                </div>
            </div>
        </body>
        </html>
        """

    async def index_handler(self, request):
        """Overview page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        uptime_hours = summary.get('uptime_seconds', 0) / 3600

        # Calculate some overview stats
        total_events = sum(summary.get('events', {}).values())
        total_errors = sum(summary.get('errors', {}).values())
        error_rate = (total_errors / total_events * 100) if total_events > 0 else 0

        content = f"""
        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-label">System Status</div>
                <div class="metric-value status-ok">ONLINE</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Uptime</div>
                <div class="metric-value">{uptime_hours:.1f}h</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Total Events</div>
                <div class="metric-value">{total_events:,}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Error Rate</div>
                <div class="metric-value {'status-ok' if error_rate < 1 else 'status-warning' if error_rate < 5 else 'status-error'}">
                    {error_rate:.2f}%
                </div>
            </div>
        </div>

        <div class="chart">
            <h2>Quick Stats</h2>
            <p>System is running smoothly with {total_events} processed events and {total_errors} errors.</p>
            <p>Last update: {summary.get('timestamp', 'N/A')}</p>
        </div>
        """

        html = self._get_base_html("Overview", content, "overview")
        return web.Response(text=html, content_type='text/html')

    async def events_handler(self, request):
        """Events page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        events = summary.get('events', {})

        content = "<h2>📊 Event Statistics</h2>"
        content += '<div class="metric-grid">'

        for event, count in sorted(events.items(), key=lambda x: x[1], reverse=True):
            content += f"""
            <div class="metric-card">
                <div class="metric-label">{event.replace('_', ' ').title()}</div>
                <div class="metric-value">{count:,}</div>
                <div class="progress-bar">
                    <div class="progress-fill" style="width: {min(count / max(events.values()) * 100, 100)}%">
                        {count}
                    </div>
                </div>
            </div>
            """

        content += '</div>'

        html = self._get_base_html("Events", content, "events")
        return web.Response(text=html, content_type='text/html')

    async def performance_handler(self, request):
        """Performance metrics page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        timings = summary.get('timings', {})

        content = "<h2>⚡ Performance Metrics</h2>"

        if timings:
            content += """
            <table>
                <thead>
                    <tr>
                        <th>Operation</th>
                        <th>Average (s)</th>
                        <th>Min (s)</th>
                        <th>Max (s)</th>
                        <th>Count</th>
                    </tr>
                </thead>
                <tbody>
            """

            for op, data in sorted(timings.items()):
                avg_class = 'status-ok' if data['avg'] < 1 else 'status-warning' if data['avg'] < 3 else 'status-error'
                content += f"""
                <tr>
                    <td><strong>{op.replace('_', ' ').title()}</strong></td>
                    <td class="{avg_class}">{data['avg']:.3f}</td>
                    <td>{data['min']:.3f}</td>
                    <td>{data['max']:.3f}</td>
                    <td>{data['count']}</td>
                </tr>
                """

            content += "</tbody></table>"
        else:
            content += "<p>No performance data available yet.</p>"

        html = self._get_base_html("Performance", content, "performance")
        return web.Response(text=html, content_type='text/html')

    async def errors_handler(self, request):
        """Errors page"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()
        errors = summary.get('errors', {})

        content = "<h2>❌ Error Tracking</h2>"

        if errors:
            content += '<div class="metric-grid">'
            for error, count in sorted(errors.items(), key=lambda x: x[1], reverse=True):
                severity_class = 'status-warning' if count < 10 else 'status-error'
                content += f"""
                <div class="metric-card">
                    <div class="metric-label">{error}</div>
                    <div class="metric-value {severity_class}">{count}</div>
                </div>
                """
            content += '</div>'
        else:
            content += '<div class="metric-card"><p class="status-ok">✅ No errors detected!</p></div>'

        html = self._get_base_html("Errors", content, "errors")
        return web.Response(text=html, content_type='text/html')

    async def dashboard_handler(self, request):
        """Main dashboard"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="Metrics not initialized", status=503)

        summary = metrics.get_metrics_summary()

        # Events summary
        events_html = ""
        if summary.get('events'):
            for event, count in list(summary['events'].items())[:5]:
                events_html += f"<li>{event}: <strong>{count}</strong></li>"

        # Errors summary
        errors_html = ""
        if summary.get('errors'):
            for error, count in summary['errors'].items():
                errors_html += f"<li class='status-error'>{error}: <strong>{count}</strong></li>"

        # Conversions
        conversions_html = ""
        if summary.get('conversions'):
            for funnel, rates in summary['conversions'].items():
                conversions_html += f"""
                <div class="metric-card">
                    <div class="metric-label">{funnel.replace('_', ' ').title()}</div>
                    {rates}
                </div>
                """

        content = f"""
        <h2>📈 Real-time Dashboard</h2>

        <div class="metric-grid">
            <div class="metric-card">
                <div class="metric-label">System Uptime</div>
                <div class="metric-value">{summary.get('uptime_seconds', 0):.0f}s</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">Last Update</div>
                <div class="metric-value" style="font-size: 1em;">
                    {summary.get('timestamp', 'N/A')}
                </div>
            </div>
        </div>

        <div class="chart">
            <h3>Top Events</h3>
            <ul>{events_html or '<li>No events yet</li>'}</ul>
        </div>

        <div class="chart">
            <h3>Recent Errors</h3>
            <ul>{errors_html or '<li class="status-ok">No errors</li>'}</ul>
        </div>

        {('<div class="chart"><h3>Conversion Funnels</h3>' + conversions_html + '</div>') if conversions_html else ''}
        """

        html = self._get_base_html("Dashboard", content, "dashboard")
        return web.Response(text=html, content_type='text/html')

    async def metrics_json(self, request):
        """Return metrics as formatted JSON"""
        metrics = get_metrics()
        if not metrics:
            return web.json_response({"error": "Metrics not initialized"}, status=503)

        summary = metrics.get_metrics_summary()

        # Pretty print JSON with syntax highlighting
        json_str = json.dumps(summary, indent=2, default=str)

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Metrics JSON</title>
            <style>
                body {{ 
                    background: #1e1e1e; 
                    color: #d4d4d4; 
                    font-family: 'Courier New', monospace;
                    padding: 20px;
                }}
                pre {{ 
                    background: #2d2d2d; 
                    padding: 20px; 
                    border-radius: 10px;
                    overflow: auto;
                }}
                .json-key {{ color: #9cdcfe; }}
                .json-value {{ color: #ce9178; }}
                .json-number {{ color: #b5cea8; }}
            </style>
        </head>
        <body>
            <h1>📊 Raw Metrics JSON</h1>
            <pre>{json_str}</pre>
            <p><a href="/" style="color: #569cd6;">← Back to Overview</a></p>
        </body>
        </html>
        """

        return web.Response(text=html, content_type='text/html')

    async def prometheus_handler(self, request):
        """Prometheus metrics"""
        metrics = get_metrics()
        if not metrics:
            return web.Response(text="# Metrics not initialized", status=503)

        prometheus_data = metrics.export_to_prometheus()

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Prometheus Metrics</title>
            <style>
                body {{ 
                    background: #f5f5f5; 
                    font-family: 'Courier New', monospace;
                    padding: 20px;
                }}
                pre {{ 
                    background: white; 
                    padding: 20px; 
                    border: 1px solid #ddd;
                    border-radius: 5px;
                    overflow: auto;
                }}
            </style>
        </head>
        <body>
            <h1>📈 Prometheus Metrics</h1>
            <pre>{prometheus_data}</pre>
            <p><a href="/">← Back to Overview</a></p>
        </body>
        </html>
        """

        return web.Response(text=html, content_type='text/html')

    async def health_check(self, request):
        """Health check endpoint"""
        health_status = {
            "status": "healthy",
            "checks": {}
        }

        try:
            with Database().session() as s:
                from sqlalchemy import text
                s.execute(text("SELECT 1"))
            health_status["checks"]["database"] = "ok"
        except Exception as e:
            health_status["checks"]["database"] = f"error: {str(e)}"
            health_status["status"] = "unhealthy"

        cache = get_cache_manager()
        if cache:
            health_status["checks"]["redis"] = "ok"
        else:
            health_status["checks"]["redis"] = "not configured"

        metrics = get_metrics()
        if metrics:
            health_status["checks"]["metrics"] = "ok"
            health_status["uptime"] = metrics.get_metrics_summary()["uptime_seconds"]

        status_code = 200 if health_status["status"] == "healthy" else 503
        return web.json_response(health_status, status=status_code)

    async def start(self):
        """Start monitoring server without access logs"""
        try:
            # Disable access logs
            import logging
            logging.getLogger('aiohttp.access').setLevel(logging.WARNING)

            self.runner = web.AppRunner(
                self.app,
                access_log=None  # Disable access logs
            )
            await self.runner.setup()
            site = web.TCPSite(self.runner, self.host, self.port)
            await site.start()
            logger.info(f"Monitoring server started on http://{self.host}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to start monitoring server: {e}")

    async def stop(self):
        """Stop server"""
        if self.runner:
            await self.runner.cleanup()
            logger.info("Monitoring server stopped")
