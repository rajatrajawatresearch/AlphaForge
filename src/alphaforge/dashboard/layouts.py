"""Dashboard page layouts."""

from dash import dcc, html, dash_table


def create_header():
    return html.Div(className="main-header", children=[
        html.Div(className="header-title", children="ALPHAFORGE"),
        html.Div(id="header-status", className="header-status", children="Initializing..."),
    ])


def create_overview_tab():
    return html.Div(style={"padding": "20px"}, children=[
        # Metric cards row
        html.Div(style={"display": "flex", "justifyContent": "space-around", "flexWrap": "wrap"}, children=[
            _metric_card("total-pnl", "Total P&L", "₹0"),
            _metric_card("realized-pnl", "Realized P&L", "₹0"),
            _metric_card("unrealized-pnl", "Unrealized P&L", "₹0"),
            _metric_card("capital-used", "Capital Used", "0%"),
            _metric_card("open-positions", "Open Positions", "0"),
            _metric_card("trades-today", "Trades Today", "0"),
        ]),

        # P&L curve chart
        html.Div(style={"marginTop": "20px"}, children=[
            dcc.Graph(
                id="pnl-chart",
                config={"displayModeBar": False},
                style={"height": "400px"},
            ),
        ]),

        # Strategy allocation pie
        html.Div(style={"display": "flex", "gap": "20px", "marginTop": "20px"}, children=[
            html.Div(style={"flex": "1"}, children=[
                dcc.Graph(id="strategy-pie", config={"displayModeBar": False}, style={"height": "300px"}),
            ]),
            html.Div(style={"flex": "1"}, children=[
                dcc.Graph(id="pnl-by-strategy", config={"displayModeBar": False}, style={"height": "300px"}),
            ]),
        ]),
    ])


def create_positions_tab():
    return html.Div(style={"padding": "20px"}, children=[
        html.H3("Open Positions", style={"color": "#9ca3af", "marginBottom": "15px"}),
        dash_table.DataTable(
            id="positions-table",
            columns=[
                {"name": "Symbol", "id": "symbol"},
                {"name": "Exchange", "id": "exchange"},
                {"name": "Qty", "id": "quantity"},
                {"name": "Avg Price", "id": "avg_price", "type": "numeric", "format": {"specifier": ",.2f"}},
                {"name": "LTP", "id": "ltp", "type": "numeric", "format": {"specifier": ",.2f"}},
                {"name": "P&L", "id": "pnl", "type": "numeric", "format": {"specifier": ",.2f"}},
                {"name": "Strategy", "id": "strategy"},
                {"name": "SL", "id": "stop_loss", "type": "numeric", "format": {"specifier": ",.2f"}},
                {"name": "Target", "id": "target", "type": "numeric", "format": {"specifier": ",.2f"}},
            ],
            data=[],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": "#1f2937", "color": "#9ca3af", "fontWeight": "bold"},
            style_cell={"backgroundColor": "#111827", "color": "#e0e6ed", "border": "1px solid #1f2937",
                         "padding": "8px", "fontSize": "13px"},
            style_data_conditional=[
                {"if": {"filter_query": "{pnl} > 0", "column_id": "pnl"},
                 "color": "#10b981", "fontWeight": "bold"},
                {"if": {"filter_query": "{pnl} < 0", "column_id": "pnl"},
                 "color": "#ef4444", "fontWeight": "bold"},
            ],
        ),
    ])


def create_orders_tab():
    return html.Div(style={"padding": "20px"}, children=[
        html.H3("Order History", style={"color": "#9ca3af", "marginBottom": "15px"}),
        dash_table.DataTable(
            id="orders-table",
            columns=[
                {"name": "Time", "id": "time"},
                {"name": "Symbol", "id": "symbol"},
                {"name": "Type", "id": "type"},
                {"name": "Qty", "id": "quantity"},
                {"name": "Price", "id": "price", "type": "numeric", "format": {"specifier": ",.2f"}},
                {"name": "Status", "id": "status"},
                {"name": "Strategy", "id": "strategy"},
                {"name": "Order ID", "id": "order_id"},
            ],
            data=[],
            style_table={"overflowX": "auto"},
            style_header={"backgroundColor": "#1f2937", "color": "#9ca3af", "fontWeight": "bold"},
            style_cell={"backgroundColor": "#111827", "color": "#e0e6ed", "border": "1px solid #1f2937",
                         "padding": "8px", "fontSize": "13px"},
            style_data_conditional=[
                {"if": {"filter_query": '{type} = "BUY"', "column_id": "type"},
                 "color": "#10b981"},
                {"if": {"filter_query": '{type} = "SELL"', "column_id": "type"},
                 "color": "#ef4444"},
            ],
            page_size=20,
            sort_action="native",
        ),
    ])


def create_risk_tab():
    return html.Div(style={"padding": "20px"}, children=[
        # Kill switch
        html.Div(style={"textAlign": "center", "marginBottom": "30px", "padding": "20px",
                         "background": "#1a0000", "borderRadius": "10px", "border": "1px solid #991b1b"}, children=[
            html.H3("EMERGENCY KILL SWITCH", style={"color": "#ef4444", "marginBottom": "15px"}),
            html.Button("KILL ALL POSITIONS", id="kill-switch-btn", className="kill-switch-btn"),
            html.Div(id="kill-switch-status", style={"marginTop": "10px", "color": "#6b7280"}),
        ]),

        # Risk metrics
        html.Div(style={"display": "flex", "justifyContent": "space-around", "flexWrap": "wrap"}, children=[
            _metric_card("daily-pnl-pct", "Daily P&L %", "0.00%"),
            _metric_card("max-drawdown", "Max Drawdown", "0.00%"),
            _metric_card("sharpe-30d", "Sharpe (30d)", "0.00"),
            _metric_card("win-rate", "Win Rate", "0.0%"),
        ]),

        # Strategy P&L table
        html.Div(style={"marginTop": "20px"}, children=[
            html.H3("Per-Strategy Performance", style={"color": "#9ca3af", "marginBottom": "15px"}),
            dash_table.DataTable(
                id="strategy-table",
                columns=[
                    {"name": "Strategy", "id": "strategy"},
                    {"name": "Positions", "id": "positions"},
                    {"name": "Allocated", "id": "allocated"},
                    {"name": "Max Alloc", "id": "max_alloc"},
                    {"name": "P&L", "id": "pnl"},
                    {"name": "Status", "id": "status"},
                ],
                data=[],
                style_header={"backgroundColor": "#1f2937", "color": "#9ca3af"},
                style_cell={"backgroundColor": "#111827", "color": "#e0e6ed", "border": "1px solid #1f2937",
                             "padding": "8px"},
            ),
        ]),

        # Strategy toggles
        html.Div(style={"marginTop": "20px"}, children=[
            html.H3("Strategy Controls", style={"color": "#9ca3af", "marginBottom": "15px"}),
            html.Div(id="strategy-toggles"),
        ]),
    ])


def create_layout():
    """Build the full dashboard layout."""
    return html.Div([
        # Auto-refresh interval
        dcc.Interval(id="refresh-interval", interval=2000, n_intervals=0),

        create_header(),

        dcc.Tabs(id="main-tabs", value="overview", className="tab-container", children=[
            dcc.Tab(label="OVERVIEW", value="overview", className="custom-tab",
                    selected_className="custom-tab--selected", children=[create_overview_tab()]),
            dcc.Tab(label="POSITIONS", value="positions", className="custom-tab",
                    selected_className="custom-tab--selected", children=[create_positions_tab()]),
            dcc.Tab(label="ORDERS", value="orders", className="custom-tab",
                    selected_className="custom-tab--selected", children=[create_orders_tab()]),
            dcc.Tab(label="RISK & CONTROL", value="risk", className="custom-tab",
                    selected_className="custom-tab--selected", children=[create_risk_tab()]),
        ]),
    ])


def _metric_card(card_id: str, label: str, default_value: str):
    return html.Div(className="metric-card", style={"minWidth": "150px", "flex": "1"}, children=[
        html.Div(className="label", children=label),
        html.Div(id=card_id, className="value value-neutral", children=default_value),
    ])
