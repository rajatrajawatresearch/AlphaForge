"""Dashboard callbacks for live updates."""

import threading

import plotly.graph_objects as go
from dash import Input, Output

from ..utils.time import now_ist, is_market_open

# Thread-safe shared state
_state = {
    "pnl_history": [],
    "positions": [],
    "orders": [],
    "risk_state": {},
    "kill_switch_cb": None,
    "mode": "paper",
    "total_pnl": 0,
    "realized_pnl": 0,
    "unrealized_pnl": 0,
    "trades_today": 0,
    "capital_used_pct": 0,
}
_state_lock = threading.Lock()


def set_shared_state(state: dict):
    """Thread-safe state update from main app."""
    with _state_lock:
        _state.update(state)


def _get_state() -> dict:
    """Thread-safe shallow copy of state."""
    with _state_lock:
        return dict(_state)


def register_callbacks(app):
    """Register all Dash callbacks."""

    @app.callback(
        Output("header-status", "children"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_header(n):
        state = _get_state()
        now = now_ist()
        market = "OPEN" if is_market_open(now) else "CLOSED"
        mode = state.get("mode", "paper").upper()
        return f"{now.strftime('%H:%M:%S IST')} | Market: {market} | Mode: {mode}"

    @app.callback(
        [Output("total-pnl", "children"), Output("total-pnl", "className"),
         Output("realized-pnl", "children"), Output("unrealized-pnl", "children"),
         Output("open-positions", "children"), Output("trades-today", "children"),
         Output("capital-used", "children")],
        Input("refresh-interval", "n_intervals"),
    )
    def update_metrics(n):
        state = _get_state()
        total_pnl = state.get("total_pnl", 0)
        realized = state.get("realized_pnl", 0)
        unrealized = state.get("unrealized_pnl", 0)
        positions = state.get("positions", [])
        pos_count = len(positions) if isinstance(positions, list) else 0
        trades = state.get("trades_today", 0)
        capital_pct = state.get("capital_used_pct", 0)

        pnl_class = "value value-positive" if total_pnl >= 0 else "value value-negative"

        return (
            f"₹{total_pnl:,.2f}", pnl_class,
            f"₹{realized:,.2f}",
            f"₹{unrealized:,.2f}",
            str(pos_count),
            str(trades),
            f"{capital_pct:.1f}%",
        )

    @app.callback(
        Output("pnl-chart", "figure"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_pnl_chart(n):
        state = _get_state()
        history = state.get("pnl_history", [])

        fig = go.Figure()
        if history:
            times = [h["time"] for h in history]
            values = [h["pnl"] for h in history]

            fig.add_trace(go.Scatter(
                x=times, y=values,
                mode="lines",
                line=dict(color="#1e90ff", width=2),
                fill="tozeroy",
                fillcolor="rgba(30, 144, 255, 0.1)",
                name="P&L",
            ))

        fig.update_layout(
            title="Equity Curve",
            paper_bgcolor="#111827",
            plot_bgcolor="#111827",
            font=dict(color="#9ca3af"),
            xaxis=dict(gridcolor="#1f2937", title="Time"),
            yaxis=dict(gridcolor="#1f2937", title="P&L (₹)"),
            margin=dict(l=50, r=20, t=40, b=40),
            showlegend=False,
        )
        return fig

    @app.callback(
        Output("positions-table", "data"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_positions(n):
        state = _get_state()
        positions = state.get("positions", [])
        rows = []
        for p in positions:
            try:
                rows.append({
                    "symbol": p.tradingsymbol,
                    "exchange": p.exchange,
                    "quantity": p.quantity,
                    "avg_price": p.average_price,
                    "ltp": p.last_price,
                    "pnl": p.pnl,
                    "strategy": p.strategy_name,
                    "stop_loss": p.stop_loss or 0,
                    "target": p.target or 0,
                })
            except AttributeError:
                pass
        return rows

    @app.callback(
        Output("orders-table", "data"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_orders(n):
        state = _get_state()
        orders = state.get("orders", [])
        rows = []
        for o in orders:
            try:
                rows.append({
                    "time": o.timestamp.strftime("%H:%M:%S") if hasattr(o.timestamp, "strftime") else str(o.timestamp),
                    "symbol": o.tradingsymbol,
                    "type": o.transaction_type,
                    "quantity": o.quantity,
                    "price": o.average_price or o.price,
                    "status": o.status,
                    "strategy": o.strategy_name,
                    "order_id": o.order_id,
                })
            except AttributeError:
                pass
        return rows

    @app.callback(
        Output("strategy-pie", "figure"),
        Input("refresh-interval", "n_intervals"),
    )
    def update_strategy_pie(n):
        state = _get_state()
        risk = state.get("risk_state", {})
        limits = risk.get("strategy_limits", {})

        names = list(limits.keys()) if limits else ["No data"]
        values = [v.get("allocated", 0) for v in limits.values()] if limits else [1]

        fig = go.Figure(data=[go.Pie(
            labels=names, values=values,
            hole=0.5,
            marker_colors=["#1e90ff", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6", "#ec4899"],
        )])
        fig.update_layout(
            title="Capital Allocation",
            paper_bgcolor="#111827",
            font=dict(color="#9ca3af"),
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=True,
            legend=dict(font=dict(size=10)),
        )
        return fig

    @app.callback(
        Output("kill-switch-status", "children"),
        Input("kill-switch-btn", "n_clicks"),
        prevent_initial_call=True,
    )
    def trigger_kill_switch(n_clicks):
        state = _get_state()
        if n_clicks and state.get("kill_switch_cb"):
            state["kill_switch_cb"]()
            return "KILL SWITCH ACTIVATED — All positions being squared off"
        return "Click to activate"
