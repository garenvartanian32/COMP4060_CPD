import csv
from pathlib import Path
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import obd
from dash import Dash, html, dcc, Input, Output, ctx

PORT = "COM11"
BAUDRATE = 38400
REFRESH_MS = 2000
MAX_POINTS = 60
CSV_FILE = Path("obd_log.csv")

CAR_LABEL = "Car 1"
CAR_NAME = "Current Test Vehicle"

app = Dash(__name__, assets_folder="assets")
app.title = "OBD-II Car Dashboard"

history = []
connection = None
vin_value = "VIN unavailable"
session_started_at = None
session_active = False
session_enabled = False


def connect_adapter():
    global connection, vin_value

    try:
        connection = obd.OBD(
            portstr=PORT,
            baudrate=BAUDRATE,
            fast=False,
            timeout=30,
        )
    except Exception:
        connection = None

    vin_value = get_vin()


def restart_adapter_session():
    global connection, history, vin_value, session_started_at, session_active, session_enabled

    try:
        if connection is not None:
            connection.close()
    except Exception:
        pass

    history = []
    vin_value = "VIN unavailable"
    session_started_at = None
    session_active = False
    session_enabled = False

    connect_adapter()


def start_session():
    global history, session_started_at, session_active, session_enabled

    history = []
    session_started_at = None
    session_active = False
    session_enabled = True


def stop_session():
    global session_active, session_enabled
    session_active = False
    session_enabled = False


def is_connected():
    return connection is not None and connection.is_connected()


def safe_query(command):
    if not is_connected():
        return None
    try:
        response = connection.query(command)
        if response is None or response.is_null():
            return None
        return response.value
    except Exception:
        return None


def clean_vin(v):
    if v is None:
        return "VIN unavailable"
    text = str(v)
    if "bytearray" in text and "\\xff" in text:
        return "VIN unavailable"
    return text


def get_vin():
    if not is_connected():
        return "VIN unavailable"
    return clean_vin(safe_query(obd.commands.VIN))


def get_sample():
    if not is_connected():
        return None

    return {
        "speed": safe_query(obd.commands.SPEED),
        "rpm": safe_query(obd.commands.RPM),
        "coolant_temp": safe_query(obd.commands.COOLANT_TEMP),
        "intake_air_temp": safe_query(obd.commands.INTAKE_TEMP),
        "throttle_pos": safe_query(obd.commands.THROTTLE_POS),
        "maf": safe_query(obd.commands.MAF),
        "engine_load": safe_query(obd.commands.ENGINE_LOAD),
        "control_module_voltage": safe_query(obd.commands.CONTROL_MODULE_VOLTAGE),
    }


def numeric_value(value):
    if value is None:
        return None
    try:
        if hasattr(value, "magnitude"):
            return float(value.magnitude)
        return float(value)
    except Exception:
        return None


def format_metric(title, value):
    if value is None:
        return "N/A"

    n = numeric_value(value)
    if n is None:
        return str(value)

    if title == "Speed":
        return f"{n:.1f} km/h"
    if title == "RPM":
        return f"{n:.0f} rpm"
    if title in ("Coolant", "Intake Air"):
        return f"{n:.1f} °C"
    if title in ("Throttle", "Engine Load"):
        return f"{n:.1f} %"
    if title == "MAF":
        return f"{n:.1f} g/s"
    if title == "Voltage":
        return f"{n:.1f} V"

    return f"{n:.1f}"


def build_empty_figure(title):
    fig = go.Figure()
    fig.update_layout(
        title=title,
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        xaxis=dict(showgrid=False, zeroline=False),
        yaxis=dict(showgrid=False, zeroline=False),
    )
    fig.add_annotation(
        text="No data available yet",
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font=dict(size=18, color="lightgray"),
    )
    return fig


def styled_line_chart(df, x_col, y_col, title):
    if df.empty or y_col not in df.columns or df[y_col].dropna().empty:
        return build_empty_figure(title)

    fig = px.line(df, x=x_col, y=y_col, title=title)
    fig.update_traces(mode="lines", line=dict(width=3))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(l=30, r=30, t=55, b=30),
        title_font=dict(size=20),
        xaxis_title="Time",
        yaxis_title=title,
    )
    return fig


def styled_multi_chart(df, x_col, y_cols, title):
    usable = [col for col in y_cols if col in df.columns and not df[col].dropna().empty]
    if df.empty or not usable:
        return build_empty_figure(title)

    fig = px.line(df, x=x_col, y=usable, title=title)
    fig.update_traces(mode="lines", line=dict(width=3))
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="white"),
        margin=dict(l=30, r=30, t=55, b=30),
        title_font=dict(size=20),
        xaxis_title="Time",
        yaxis_title="Value",
        legend_title="Metric",
    )
    return fig


def metric_card(title, value, accent):
    return html.Div(
        [
            html.Div(title, className="metric-title"),
            html.Div(value, className="metric-value"),
        ],
        className="metric-card",
        style={"borderTop": f"4px solid {accent}"},
    )


def ensure_csv_exists():
    if not CSV_FILE.exists():
        with CSV_FILE.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "timestamp",
                "date",
                "time",
                "session_start",
                "car_label",
                "car_name",
                "vin",
                "speed",
                "rpm",
                "coolant_temp",
                "intake_air_temp",
                "throttle_pos",
                "maf",
                "engine_load",
                "control_module_voltage",
            ])


def append_sample_to_csv(now, sample):
    ensure_csv_exists()

    with CSV_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            now.strftime("%Y-%m-%d %H:%M:%S"),
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            session_started_at.strftime("%Y-%m-%d %H:%M:%S") if session_started_at else "",
            CAR_LABEL,
            CAR_NAME,
            vin_value,
            numeric_value(sample.get("speed")),
            numeric_value(sample.get("rpm")),
            numeric_value(sample.get("coolant_temp")),
            numeric_value(sample.get("intake_air_temp")),
            numeric_value(sample.get("throttle_pos")),
            numeric_value(sample.get("maf")),
            numeric_value(sample.get("engine_load")),
            numeric_value(sample.get("control_module_voltage")),
        ])


def ignition_or_engine_ready(sample):
    if sample is None:
        return False

    rpm = numeric_value(sample.get("rpm"))
    coolant = numeric_value(sample.get("coolant_temp"))
    voltage = numeric_value(sample.get("control_module_voltage"))

    if rpm is not None and rpm > 0:
        return True
    if coolant is not None:
        return True
    if voltage is not None and voltage > 0:
        return True

    return False


connect_adapter()
ensure_csv_exists()

app.layout = html.Div(
    className="page",
    children=[
        dcc.Interval(id="refresh", interval=REFRESH_MS, n_intervals=0),

        html.Div(className="bg-overlay"),

        html.Div(
            className="hero",
            children=[
                html.Div(
                    [
                        html.Div("OBD-II LIVE TELEMETRY", className="hero-kicker"),
                        html.H1("Vehicle Monitoring Dashboard", className="hero-title"),
                        html.P(
                            "A car-inspired live dashboard for speed, RPM, temperature, airflow, load, and electrical telemetry.",
                            className="hero-subtitle",
                        ),
                    ]
                ),
                html.Div(id="vehicle-box", className="vin-box"),
            ],
        ),

        html.Div(
            className="hero",
            style={"marginTop": "18px"},
            children=[
                html.Div(
                    [
                        html.Button(
                            "Start Session",
                            id="start-session-btn",
                            n_clicks=0,
                            className="profile-button",
                            style={"marginRight": "12px"},
                        ),
                        html.Button(
                            "Stop Session",
                            id="stop-session-btn",
                            n_clicks=0,
                            className="profile-button",
                            style={"marginRight": "12px"},
                        ),
                        html.Button(
                            "Restart Session / Reconnect Adapter",
                            id="restart-session-btn",
                            n_clicks=0,
                            className="profile-button",
                            style={"marginRight": "12px"},
                        ),
                        html.Span(
                            id="session-status",
                            style={"fontSize": "15px", "color": "#d5dbe3"},
                        ),
                    ]
                )
            ],
        ),

        html.Div(id="metric-row", className="metric-grid"),

        html.Div(
            className="charts-grid",
            children=[
                html.Div(dcc.Graph(id="speed-chart"), className="chart-card"),
                html.Div(dcc.Graph(id="rpm-chart"), className="chart-card"),
                html.Div(dcc.Graph(id="temp-chart"), className="chart-card"),
                html.Div(dcc.Graph(id="air-chart"), className="chart-card"),
                html.Div(dcc.Graph(id="load-chart"), className="chart-card"),
                html.Div(dcc.Graph(id="voltage-chart"), className="chart-card"),
            ],
        ),
    ],
)


@app.callback(
    Output("session-status", "children"),
    Input("start-session-btn", "n_clicks"),
    Input("stop-session-btn", "n_clicks"),
    Input("restart-session-btn", "n_clicks"),
    prevent_initial_call=True,
)
def handle_session_buttons(_, __, ___):
    triggered = ctx.triggered_id

    if triggered == "start-session-btn":
        start_session()
        return "Session armed. Turn ignition on / start the car to begin live capture."

    if triggered == "stop-session-btn":
        stop_session()
        return "Session stopped. Live capture paused."

    if triggered == "restart-session-btn":
        restart_adapter_session()
        return "Session restarted. Press Start Session when ready."

    return "Ready."


@app.callback(
    Output("vehicle-box", "children"),
    Output("metric-row", "children"),
    Output("speed-chart", "figure"),
    Output("rpm-chart", "figure"),
    Output("temp-chart", "figure"),
    Output("air-chart", "figure"),
    Output("load-chart", "figure"),
    Output("voltage-chart", "figure"),
    Output("session-status", "children", allow_duplicate=True),
    Input("refresh", "n_intervals"),
    prevent_initial_call=True,
)
def update_dashboard(_):
    global history, vin_value, session_started_at, session_active, session_enabled

    if not is_connected():
        vehicle_box = html.Div(
            [
                html.Div("Vehicle", style={"fontWeight": "700", "marginBottom": "6px"}),
                html.Div(CAR_LABEL, style={"fontSize": "22px", "fontWeight": "700"}),
                html.Div(CAR_NAME, style={"marginTop": "6px"}),
                html.Div("VIN: unavailable", style={"marginTop": "6px"}),
                html.Div("Status: disconnected", style={"marginTop": "8px", "color": "#ff8a8a", "fontSize": "13px"}),
            ]
        )

        metrics = [
            metric_card("Speed", "N/A", "#ff7a18"),
            metric_card("RPM", "N/A", "#00c2ff"),
            metric_card("Coolant", "N/A", "#ff4d6d"),
            metric_card("Intake Air", "N/A", "#14b8a6"),
            metric_card("Throttle", "N/A", "#8b5cf6"),
            metric_card("Voltage", "N/A", "#ffd166"),
        ]

        empty = build_empty_figure("No live connection")
        return vehicle_box, metrics, empty, empty, empty, empty, empty, empty, "Adapter disconnected."

    if not session_enabled:
        vehicle_box = html.Div(
            [
                html.Div("Vehicle", style={"fontWeight": "700", "marginBottom": "6px"}),
                html.Div(CAR_LABEL, style={"fontSize": "22px", "fontWeight": "700"}),
                html.Div(CAR_NAME, style={"marginTop": "6px"}),
                html.Div(f"VIN: {vin_value}", style={"marginTop": "6px", "wordBreak": "break-all"}),
                html.Div("Status: waiting to start", style={"marginTop": "8px", "color": "#ffd166", "fontSize": "13px"}),
            ]
        )

        metrics = [
            metric_card("Speed", "N/A", "#ff7a18"),
            metric_card("RPM", "N/A", "#00c2ff"),
            metric_card("Coolant", "N/A", "#ff4d6d"),
            metric_card("Intake Air", "N/A", "#14b8a6"),
            metric_card("Throttle", "N/A", "#8b5cf6"),
            metric_card("Voltage", "N/A", "#ffd166"),
        ]

        empty = build_empty_figure("Press Start Session to begin")
        return vehicle_box, metrics, empty, empty, empty, empty, empty, empty, "Press Start Session to begin polling."

    now = datetime.now()
    sample = get_sample()

    if sample is None:
        empty = build_empty_figure("No live data")
        return html.Div("No live data"), [], empty, empty, empty, empty, empty, empty, "No live data from ECU yet."

    vin_value = get_vin()

    ready = ignition_or_engine_ready(sample)

    if not session_active and ready:
        session_active = True
        session_started_at = now

    if not session_active:
        empty = build_empty_figure("Waiting for ignition / engine data")
        vehicle_box = html.Div(
            [
                html.Div("Vehicle", style={"fontWeight": "700", "marginBottom": "6px"}),
                html.Div(CAR_LABEL, style={"fontSize": "22px", "fontWeight": "700"}),
                html.Div(CAR_NAME, style={"marginTop": "6px"}),
                html.Div(f"VIN: {vin_value}", style={"marginTop": "6px", "wordBreak": "break-all"}),
                html.Div(
                    "Status: armed, waiting for ignition/engine data",
                    style={"marginTop": "8px", "color": "#ffd166", "fontSize": "13px"},
                ),
            ]
        )

        metrics = [
            metric_card("Speed", format_metric("Speed", sample.get("speed")), "#ff7a18"),
            metric_card("RPM", format_metric("RPM", sample.get("rpm")), "#00c2ff"),
            metric_card("Coolant", format_metric("Coolant", sample.get("coolant_temp")), "#ff4d6d"),
            metric_card("Intake Air", format_metric("Intake Air", sample.get("intake_air_temp")), "#14b8a6"),
            metric_card("Throttle", format_metric("Throttle", sample.get("throttle_pos")), "#8b5cf6"),
            metric_card("Voltage", format_metric("Voltage", sample.get("control_module_voltage")), "#ffd166"),
        ]

        return vehicle_box, metrics, empty, empty, empty, empty, empty, empty, "Session armed. Waiting for ignition/engine response..."

    row = {
        "timestamp": now,
        "speed": numeric_value(sample["speed"]),
        "rpm": numeric_value(sample["rpm"]),
        "coolant_temp": numeric_value(sample["coolant_temp"]),
        "intake_air_temp": numeric_value(sample["intake_air_temp"]),
        "throttle_pos": numeric_value(sample["throttle_pos"]),
        "maf": numeric_value(sample["maf"]),
        "engine_load": numeric_value(sample["engine_load"]),
        "control_module_voltage": numeric_value(sample["control_module_voltage"]),
    }

    history.append(row)
    history = history[-MAX_POINTS:]
    append_sample_to_csv(now, sample)

    df = pd.DataFrame(history)

    vehicle_box = html.Div(
        [
            html.Div("Vehicle", style={"fontWeight": "700", "marginBottom": "6px"}),
            html.Div(CAR_LABEL, style={"fontSize": "22px", "fontWeight": "700"}),
            html.Div(CAR_NAME, style={"marginTop": "6px"}),
            html.Div(f"VIN: {vin_value}", style={"marginTop": "6px", "wordBreak": "break-all"}),
            html.Div(
                f"Last update: {now.strftime('%Y-%m-%d %H:%M:%S')}",
                style={"marginTop": "8px", "color": "#d5dbe3", "fontSize": "13px"},
            ),
        ]
    )

    metrics = [
        metric_card("Speed", format_metric("Speed", sample.get("speed")), "#ff7a18"),
        metric_card("RPM", format_metric("RPM", sample.get("rpm")), "#00c2ff"),
        metric_card("Coolant", format_metric("Coolant", sample.get("coolant_temp")), "#ff4d6d"),
        metric_card("Intake Air", format_metric("Intake Air", sample.get("intake_air_temp")), "#14b8a6"),
        metric_card("Throttle", format_metric("Throttle", sample.get("throttle_pos")), "#8b5cf6"),
        metric_card("Voltage", format_metric("Voltage", sample.get("control_module_voltage")), "#ffd166"),
    ]

    speed_fig = styled_line_chart(df, "timestamp", "speed", "Vehicle Speed")
    rpm_fig = styled_line_chart(df, "timestamp", "rpm", "Engine RPM")
    temp_fig = styled_multi_chart(df, "timestamp", ["coolant_temp", "intake_air_temp"], "Temperatures")
    air_fig = styled_line_chart(df, "timestamp", "maf", "Mass Air Flow")
    load_fig = styled_multi_chart(df, "timestamp", ["engine_load", "throttle_pos"], "Load & Throttle")
    voltage_fig = styled_line_chart(df, "timestamp", "control_module_voltage", "Control Module Voltage")

    return (
        vehicle_box,
        metrics,
        speed_fig,
        rpm_fig,
        temp_fig,
        air_fig,
        load_fig,
        voltage_fig,
        f"Session active since {session_started_at.strftime('%Y-%m-%d %H:%M:%S')}",
    )


if __name__ == "__main__":
    app.run(debug=False)