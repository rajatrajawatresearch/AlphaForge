"""Dash dashboard application factory."""

import logging
import threading

from dash import Dash

from .callbacks import register_callbacks, set_shared_state
from .layouts import create_layout

logger = logging.getLogger("alphaforge.dashboard")


class DashboardApp:
    """Live monitoring dashboard for AlphaForge."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8050):
        self.host = host
        self.port = port
        self._app: Dash | None = None
        self._thread: threading.Thread | None = None

    def create_app(self) -> Dash:
        """Create and configure the Dash application."""
        app = Dash(
            __name__,
            title="AlphaForge Dashboard",
            assets_folder="assets",
            suppress_callback_exceptions=True,
        )
        app.layout = create_layout()
        register_callbacks(app)
        self._app = app
        return app

    def start(self, shared_state: dict | None = None) -> None:
        """Start the dashboard in a background thread."""
        if shared_state:
            set_shared_state(shared_state)

        if self._app is None:
            self.create_app()

        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="dashboard-thread",
        )
        self._thread.start()
        logger.info("Dashboard started at http://%s:%d", self.host, self.port)

    def _run(self):
        """Run the Dash server (blocking, runs in thread)."""
        self._app.run(
            host=self.host,
            port=self.port,
            debug=False,
            use_reloader=False,
        )

    def update_state(self, key: str, value) -> None:
        """Update shared state for dashboard callbacks."""
        set_shared_state({key: value})
