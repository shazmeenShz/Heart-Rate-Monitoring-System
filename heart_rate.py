
import sys
import re
import math
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime

try:
    import serial
    from serial.tools import list_ports
except Exception as exc:
    raise SystemExit(
        "pyserial is required. Install it with: pip install pyserial"
    ) from exc

try:
    from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QSize, QPointF
    from PySide6.QtGui import QColor, QFont, QAction, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFrame,
        QGridLayout,
        QGraphicsDropShadowEffect,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QPlainTextEdit,
        QProgressBar,
        QSizePolicy,
        QSpacerItem,
        QSpinBox,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
        QSplitter,
        QFormLayout,
        QToolButton,
    )
except Exception as exc:
    raise SystemExit(
        "PySide6 is required. Install it with: pip install PySide6 pyqtgraph"
    ) from exc

try:
    import pyqtgraph as pg
except Exception as exc:
    raise SystemExit(
        "pyqtgraph is required. Install it with: pip install pyqtgraph"
    ) from exc


APP_NAME = "Pulse Studio"
DEFAULT_BAUD = 9600
BAUD_PRESETS = [9600, 19200, 38400, 57600, 115200, 230400]
THEME = {
    "bg": "#111315",
    "panel": "#171A1F",
    "panel2": "#1C2026",
    "panel3": "#232830",
    "text": "#E8EDF2",
    "muted": "#9AA4AF",
    "muted2": "#74808C",
    "accent": "#3CC6FF",
    "accent2": "#27D8C8",
    "success": "#2FD07F",
    "warning": "#E4AF3D",
    "danger": "#EE6B6B",
    "border": "#2A313A",
    "grid": "#26303A",
}


def available_ports() -> list[str]:
    ports = []
    for p in list_ports.comports():
        label = p.device
        if p.description:
            label = f"{p.device} — {p.description}"
        ports.append(label)
    return ports


def extract_port_device(display_text: str) -> str:
    return display_text.split(" — ", 1)[0].strip()


def parse_telemetry_line(line: str) -> dict | None:
    """
    Parses lines like:
      HR=78 SYS=120 DIA=80 SpO2=98% | NORMAL BP
      HR: 72 BPM SYS: 118 DIA: 77 SpO2: 97
      <78,98,52100>  (future format support; interpreted conservatively)
    """
    raw = line.strip()
    if not raw:
        return None

    data = {
        "raw": raw,
        "timestamp": datetime.now(),
    }

    # Key-value style telemetry from the firmware in the uploaded sketch.
    kv_patterns = {
        "hr": r"(?:HR|BPM)\s*[:=]\s*(\d+)",
        "sys": r"(?:SYS|SYSBP|SYSTOLIC)\s*[:=]\s*(\d+)",
        "dia": r"(?:DIA|DIASTOLIC)\s*[:=]\s*(\d+)",
        "spo2": r"(?:SpO2|SPO2)\s*[:=]\s*(\d+)",
    }
    matched_any = False
    for key, pattern in kv_patterns.items():
        m = re.search(pattern, raw, re.IGNORECASE)
        if m:
            data[key] = int(m.group(1))
            matched_any = True

    # Status keywords
    if re.search(r"\bLOW BP\b", raw, re.IGNORECASE):
        data["status"] = "LOW"
        matched_any = True
    elif re.search(r"\bHIGH BP\b", raw, re.IGNORECASE):
        data["status"] = "HIGH"
        matched_any = True
    elif re.search(r"\bNORMAL BP\b", raw, re.IGNORECASE):
        data["status"] = "NORMAL"
        matched_any = True
    elif re.search(r"\bCONNECTED\b", raw, re.IGNORECASE):
        data["status"] = "CONNECTED"
        matched_any = True

    # Generic angle-bracket packet support. This is intentionally conservative.
    # If the firmware changes later, this keeps the GUI from breaking.
    if raw.startswith("<") and raw.endswith(">"):
        parts = [p.strip() for p in raw[1:-1].split(",") if p.strip()]
        try:
            nums = [float(p) for p in parts]
            data["packet"] = nums
            matched_any = True
            if len(nums) >= 1 and "hr" not in data:
                data["hr"] = int(round(nums[0]))
            if len(nums) >= 2 and "spo2" not in data:
                data["spo2"] = int(round(nums[1]))
        except ValueError:
            pass

    return data if matched_any else None


class SerialWorker(QThread):
    telemetry = Signal(dict)
    raw_line = Signal(str)
    status = Signal(str)
    connected = Signal(str, int)
    disconnected = Signal()

    def __init__(self, port: str, baud: int, parent=None):
        super().__init__(parent)
        self.port = port
        self.baud = baud
        self._running = True
        self._serial = None
        self._write_lock = False

    def stop(self):
        self._running = False
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass

    @Slot(str)
    def send_text(self, text: str):
        try:
            if self._serial and self._serial.is_open:
                payload = text.encode("utf-8")
                self._serial.write(payload)
                self._serial.flush()
        except Exception as exc:
            self.status.emit(f"Command error: {exc}")

    def run(self):
        try:
            self._serial = serial.Serial(self.port, self.baud, timeout=0.12)
            self._serial.reset_input_buffer()
            self._serial.reset_output_buffer()
            self.connected.emit(self.port, self.baud)
            self.status.emit(f"Connected to {self.port} @ {self.baud}")
        except Exception as exc:
            self.status.emit(f"Connection failed: {exc}")
            self.disconnected.emit()
            return

        buffer = ""
        while self._running:
            try:
                if not self._serial or not self._serial.is_open:
                    break
                chunk = self._serial.read(256)
                if not chunk:
                    continue
                try:
                    text = chunk.decode(errors="ignore")
                except Exception:
                    text = ""
                if not text:
                    continue

                buffer += text
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.replace("\r", "").strip()
                    if not line:
                        continue
                    self.raw_line.emit(line)
                    packet = parse_telemetry_line(line)
                    if packet:
                        self.telemetry.emit(packet)
            except Exception as exc:
                self.status.emit(f"Serial read error: {exc}")
                break

        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:
            pass
        self.disconnected.emit()


class MetricCard(QFrame):
    def __init__(self, title: str, unit: str = "", subtitle: str = "", big: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("MetricCard")
        self.setProperty("class", "card")
        self.setMinimumHeight(120 if big else 96)
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        self.value = QLabel("--")
        self.value.setObjectName("CardValue")
        self.unit = QLabel(unit)
        self.unit.setObjectName("CardUnit")
        self.subtitle = QLabel(subtitle)
        self.subtitle.setObjectName("CardSubtitle")

        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(self.title)
        top.addStretch(1)
        top.addWidget(self.unit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)
        layout.addLayout(top)
        layout.addWidget(self.value)
        layout.addWidget(self.subtitle)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(22)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(shadow)

    def set_value(self, value: str):
        self.value.setText(value)

    def set_subtitle(self, text: str):
        self.subtitle.setText(text)

    def set_accent(self, color: str):
        self.setStyleSheet(
            f"""
            QFrame#MetricCard {{
                background: {THEME["panel"]};
                border: 1px solid {THEME["border"]};
                border-radius: 18px;
            }}
            QLabel#CardTitle {{
                color: {THEME["muted"]};
                font-size: 12px;
                font-weight: 600;
                letter-spacing: 0.6px;
                text-transform: uppercase;
            }}
            QLabel#CardValue {{
                color: {THEME["text"]};
                font-size: 34px;
                font-weight: 700;
            }}
            QLabel#CardUnit {{
                color: {color};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#CardSubtitle {{
                color: {THEME["muted2"]};
                font-size: 12px;
            }}
            """
        )


class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connect Device")
        self.setModal(True)
        self.setMinimumWidth(420)

        self.port_combo = QComboBox()
        self.port_combo.setEditable(False)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.refresh_ports)

        port_row = QHBoxLayout()
        port_row.addWidget(self.port_combo, 1)
        port_row.addWidget(self.refresh_btn)

        self.baud_combo = QComboBox()
        self.baud_combo.setEditable(False)
        for baud in BAUD_PRESETS:
            self.baud_combo.addItem(str(baud), baud)
        default_index = self.baud_combo.findData(DEFAULT_BAUD)
        if default_index >= 0:
            self.baud_combo.setCurrentIndex(default_index)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.addRow("Serial Port", port_row)
        form.addRow("Baud Rate", self.baud_combo)

        self.info = QLabel(
            "Choose the serial port before the dashboard starts. The default baud rate matches the firmware."
        )
        self.info.setWordWrap(True)
        self.info.setObjectName("DialogInfo")

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Ok)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(self.info)
        layout.addLayout(form)
        layout.addWidget(self.buttons)

        self.refresh_ports()

    def refresh_ports(self):
        current = self.port_combo.currentText()
        self.port_combo.clear()
        ports = available_ports()
        if ports:
            self.port_combo.addItems(ports)
            idx = self.port_combo.findText(current)
            if idx >= 0:
                self.port_combo.setCurrentIndex(idx)
        else:
            self.port_combo.addItem("No serial devices found")

    def selected_port(self) -> str:
        return extract_port_device(self.port_combo.currentText())

    def selected_baud(self) -> int:
        return int(self.baud_combo.currentData())


class PulseSynth:
    """
    Creates a polished preview trace from BPM. The device currently sends
    summary telemetry, so this gives the dashboard a live medical-monitor feel
    without pretending to be raw ECG data.
    """
    def __init__(self, length: int = 420):
        self.length = length
        self.buffer = deque([0.0] * length, maxlen=length)
        self.phase = 0.0
        self.next_beat_t = time.monotonic()
        self.last_bpm = 72.0
        self.jitter = 0.0
        self.flash = 0.0

    def set_bpm(self, bpm: float):
        if bpm and bpm > 0:
            self.last_bpm = float(bpm)

    def beat_now(self):
        self.flash = 1.0

    def step(self):
        bpm = max(35.0, min(180.0, float(self.last_bpm)))
        period = 60.0 / bpm
        now = time.monotonic()
        if now >= self.next_beat_t:
            self.next_beat_t = now + period
            self.beat_now()

        self.phase += 1.0 / max(1.0, period * 50.0)

        x = (self.phase % 1.0)
        baseline = 0.02 * math.sin(self.phase * math.tau * 1.5)
        pulse = 0.0

        # A compact pulse template with a sharp QRS-like peak.
        if x < 0.12:
            pulse = 0.0
        elif x < 0.18:
            pulse = 0.06 * (x - 0.12) / 0.06
        elif x < 0.21:
            pulse = -0.08 + 0.08 * (x - 0.18) / 0.03
        elif x < 0.23:
            pulse = 0.95 * (1.0 - abs((x - 0.21) / 0.02))
        elif x < 0.28:
            pulse = -0.16 + 0.16 * (x - 0.23) / 0.05
        elif x < 0.45:
            pulse = 0.04 * math.sin((x - 0.28) / 0.17 * math.pi)
        elif x < 0.72:
            pulse = 0.02 * math.sin((x - 0.45) / 0.27 * math.pi * 0.7)
        else:
            pulse = 0.0

        if self.flash > 0:
            pulse += 0.18 * self.flash
            self.flash *= 0.82

        value = baseline + pulse
        self.buffer.append(value)

    def data(self):
        y = list(self.buffer)
        x = list(range(len(y)))
        return x, y


class MainWindow(QMainWindow):
    def __init__(self, port: str, baud: int):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(1300, 820)

        self.port = port
        self.baud = baud
        self.worker = None
        self.serial_ok = False
        self.last_packet_at = 0.0
        self.latest = {
            "hr": None,
            "sys": None,
            "dia": None,
            "spo2": None,
            "status": "WAITING",
            "raw": "",
        }
        self.synth = PulseSynth()

        self._build_ui()
        self._apply_theme()
        self._build_menu()
        self._build_timers()
        self.start_connection(port, baud)

    def _build_menu(self):
        file_menu = self.menuBar().addMenu("Device")
        reconnect = QAction("Reconnect", self)
        reconnect.triggered.connect(self.reconnect)
        disconnect = QAction("Disconnect", self)
        disconnect.triggered.connect(self.disconnect_device)
        exit_act = QAction("Exit", self)
        exit_act.triggered.connect(self.close)
        file_menu.addAction(reconnect)
        file_menu.addAction(disconnect)
        file_menu.addSeparator()
        file_menu.addAction(exit_act)

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        header = QFrame()
        header.setObjectName("HeaderPanel")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(16)

        title_box = QVBoxLayout()
        title = QLabel("Pulse Studio")
        title.setObjectName("AppTitle")
        subtitle = QLabel("Live heartbeat telemetry, serial health, and status visualization")
        subtitle.setObjectName("AppSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        self.conn_pill = QLabel("DISCONNECTED")
        self.conn_pill.setObjectName("StatusPill")

        self.port_label = QLabel(f"Port: {self.port}")
        self.port_label.setObjectName("MetaLabel")
        self.baud_label = QLabel(f"Baud: {self.baud}")
        self.baud_label.setObjectName("MetaLabel")
        meta_box = QVBoxLayout()
        meta_box.setSpacing(4)
        meta_box.addWidget(self.port_label)
        meta_box.addWidget(self.baud_label)

        self.reconnect_btn = QPushButton("Reconnect")
        self.reconnect_btn.clicked.connect(self.reconnect)
        self.disconnect_btn = QPushButton("Disconnect")
        self.disconnect_btn.clicked.connect(self.disconnect_device)

        header_layout.addLayout(title_box, 1)
        header_layout.addWidget(self.conn_pill)
        header_layout.addSpacing(10)
        header_layout.addLayout(meta_box)
        header_layout.addSpacing(8)
        header_layout.addWidget(self.reconnect_btn)
        header_layout.addWidget(self.disconnect_btn)

        outer.addWidget(header)

        body = QSplitter(Qt.Horizontal)
        body.setHandleWidth(10)
        body.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self.card_hr = MetricCard("Heart Rate", "BPM", "Waiting for telemetry", big=True)
        self.card_hr.set_accent(THEME["accent"])
        self.card_sys = MetricCard("Systolic", "mmHg", "Waiting for telemetry")
        self.card_sys.set_accent(THEME["success"])
        self.card_dia = MetricCard("Diastolic", "mmHg", "Waiting for telemetry")
        self.card_dia.set_accent(THEME["accent2"])
        self.card_spo2 = MetricCard("SpO2", "%", "Waiting for telemetry")
        self.card_spo2.set_accent(THEME["warning"])

        grid.addWidget(self.card_hr, 0, 0)
        grid.addWidget(self.card_sys, 0, 1)
        grid.addWidget(self.card_dia, 1, 0)
        grid.addWidget(self.card_spo2, 1, 1)

        self.health_card = QFrame()
        self.health_card.setObjectName("HealthCard")
        health_layout = QVBoxLayout(self.health_card)
        health_layout.setContentsMargins(18, 16, 18, 16)
        health_layout.setSpacing(12)

        hl_top = QHBoxLayout()
        self.health_title = QLabel("Connection health")
        self.health_title.setObjectName("PanelTitle")
        self.health_state = QLabel("No data yet")
        self.health_state.setObjectName("HealthState")
        hl_top.addWidget(self.health_title)
        hl_top.addStretch(1)
        hl_top.addWidget(self.health_state)

        self.health_bar = QProgressBar()
        self.health_bar.setRange(0, 100)
        self.health_bar.setValue(0)
        self.health_bar.setTextVisible(False)

        self.status_desc = QLabel(
            "The dashboard will light up once the first telemetry line arrives."
        )
        self.status_desc.setWordWrap(True)
        self.status_desc.setObjectName("BodyText")

        health_layout.addLayout(hl_top)
        health_layout.addWidget(self.health_bar)
        health_layout.addWidget(self.status_desc)

        self.command_box = QFrame()
        self.command_box.setObjectName("CommandBox")
        cmd_layout = QVBoxLayout(self.command_box)
        cmd_layout.setContentsMargins(18, 16, 18, 16)
        cmd_layout.setSpacing(12)

        cmd_head = QHBoxLayout()
        cmd_title = QLabel("Firmware commands")
        cmd_title.setObjectName("PanelTitle")
        cmd_note = QLabel("Uses the firmware's serial commands")
        cmd_note.setObjectName("HintText")
        cmd_head.addWidget(cmd_title)
        cmd_head.addStretch(1)
        cmd_head.addWidget(cmd_note)

        btn_row = QHBoxLayout()
        self.btn_low = QPushButton("Force LOW BP")
        self.btn_high = QPushButton("Force HIGH BP")
        self.btn_normal = QPushButton("Auto / Normal")
        self.btn_scan = QPushButton("Run I2C scan")

        self.btn_low.clicked.connect(lambda: self.send_command("L"))
        self.btn_high.clicked.connect(lambda: self.send_command("H"))
        self.btn_normal.clicked.connect(lambda: self.send_command("N"))
        self.btn_scan.clicked.connect(lambda: self.send_command("I"))

        for b in (self.btn_low, self.btn_high, self.btn_normal, self.btn_scan):
            b.setMinimumHeight(42)
            btn_row.addWidget(b)

        cmd_layout.addLayout(cmd_head)
        cmd_layout.addLayout(btn_row)

        left_layout.addLayout(grid)
        left_layout.addWidget(self.health_card)
        left_layout.addWidget(self.command_box)
        left_layout.addStretch(1)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(14)

        plot_card = QFrame()
        plot_card.setObjectName("PlotCard")
        plot_layout = QVBoxLayout(plot_card)
        plot_layout.setContentsMargins(18, 16, 18, 18)
        plot_layout.setSpacing(10)

        plot_header = QHBoxLayout()
        plot_title = QLabel("Pulse rhythm preview")
        plot_title.setObjectName("PanelTitle")
        plot_hint = QLabel("Animated from BPM telemetry")
        plot_hint.setObjectName("HintText")
        plot_header.addWidget(plot_title)
        plot_header.addStretch(1)
        plot_header.addWidget(plot_hint)

        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.setBackground(None)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.setYRange(-0.28, 1.05)
        self.plot.setXRange(0, self.synth.length - 1)
        self.plot.getPlotItem().hideAxis("bottom")
        self.plot.getPlotItem().hideAxis("left")
        self.plot.setMinimumHeight(420)

        pen = pg.mkPen(QColor(THEME["accent"]), width=2.5)
        self.wave_curve = self.plot.plot([], [], pen=pen)
        self.wave_curve.setClipToView(True)

        self.plot_note = QLabel(
            "This line is a live rhythm visualization driven by the serial BPM stream."
        )
        self.plot_note.setObjectName("BodyText")

        plot_layout.addLayout(plot_header)
        plot_layout.addWidget(self.plot, 1)
        plot_layout.addWidget(self.plot_note)

        log_card = QFrame()
        log_card.setObjectName("LogCard")
        log_layout = QVBoxLayout(log_card)
        log_layout.setContentsMargins(18, 16, 18, 18)
        log_layout.setSpacing(10)

        log_header = QHBoxLayout()
        log_title = QLabel("Serial console")
        log_title.setObjectName("PanelTitle")
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(lambda: self.console.clear())
        log_header.addWidget(log_title)
        log_header.addStretch(1)
        log_header.addWidget(self.clear_btn)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(1000)
        self.console.setPlaceholderText("Incoming serial data will appear here...")

        log_layout.addLayout(log_header)
        log_layout.addWidget(self.console, 1)

        right_layout.addWidget(plot_card, 2)
        right_layout.addWidget(log_card, 1)

        body.addWidget(left)
        body.addWidget(right)
        body.setStretchFactor(0, 1)
        body.setStretchFactor(1, 2)

        outer.addWidget(body, 1)

        self._all_buttons = [
            self.reconnect_btn,
            self.disconnect_btn,
            self.btn_low,
            self.btn_high,
            self.btn_normal,
            self.btn_scan,
            self.clear_btn,
        ]

    def _build_timers(self):
        self.visual_timer = QTimer(self)
        self.visual_timer.timeout.connect(self._tick_visuals)
        self.visual_timer.start(20)

        self.health_timer = QTimer(self)
        self.health_timer.timeout.connect(self._tick_health)
        self.health_timer.start(250)

    def _apply_theme(self):
        self.setStyleSheet(
            f"""
            QMainWindow {{
                background: {THEME["bg"]};
            }}
            QWidget {{
                color: {THEME["text"]};
                font-family: Inter, Segoe UI, system-ui, sans-serif;
                font-size: 13px;
            }}
            QMenuBar {{
                background: transparent;
                color: {THEME["text"]};
                padding: 6px;
            }}
            QMenuBar::item {{
                background: transparent;
                padding: 6px 10px;
                border-radius: 8px;
            }}
            QMenuBar::item:selected {{
                background: {THEME["panel2"]};
            }}
            QMenu {{
                background: {THEME["panel2"]};
                color: {THEME["text"]};
                border: 1px solid {THEME["border"]};
            }}
            QMenu::item:selected {{
                background: {THEME["accent"]};
                color: #001018;
            }}
            QFrame#HeaderPanel,
            QFrame#PlotCard,
            QFrame#LogCard,
            QFrame#HealthCard,
            QFrame#CommandBox {{
                background: {THEME["panel"]};
                border: 1px solid {THEME["border"]};
                border-radius: 20px;
            }}
            QLabel#AppTitle {{
                font-size: 30px;
                font-weight: 700;
                letter-spacing: 0.2px;
            }}
            QLabel#AppSubtitle {{
                color: {THEME["muted"]};
                font-size: 13px;
            }}
            QLabel#MetaLabel {{
                color: {THEME["muted"]};
                font-size: 12px;
            }}
            QLabel#StatusPill {{
                background: rgba(60, 198, 255, 0.12);
                color: {THEME["accent"]};
                border: 1px solid rgba(60, 198, 255, 0.28);
                border-radius: 999px;
                padding: 8px 12px;
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#PanelTitle {{
                color: {THEME["text"]};
                font-size: 14px;
                font-weight: 700;
            }}
            QLabel#HintText {{
                color: {THEME["muted2"]};
                font-size: 12px;
            }}
            QLabel#BodyText {{
                color: {THEME["muted"]};
                font-size: 13px;
            }}
            QLabel#HealthState {{
                color: {THEME["accent"]};
                font-size: 12px;
                font-weight: 700;
            }}
            QLabel#DialogInfo {{
                color: {THEME["muted"]};
                font-size: 13px;
            }}
            QPushButton {{
                background: {THEME["panel3"]};
                color: {THEME["text"]};
                border: 1px solid {THEME["border"]};
                border-radius: 12px;
                padding: 10px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: #2a3038;
                border-color: #37414d;
            }}
            QPushButton:pressed {{
                background: #313844;
            }}
            QPushButton:disabled {{
                color: #7b838c;
                background: #191c21;
            }}
            QPushButton[text="Reconnect"] {{
                background: rgba(60, 198, 255, 0.12);
                border: 1px solid rgba(60, 198, 255, 0.25);
                color: {THEME["accent"]};
            }}
            QPushButton[text="Reconnect"]:hover {{
                background: rgba(60, 198, 255, 0.18);
            }}
            QPushButton[text="Force LOW BP"] {{
                background: rgba(238, 107, 107, 0.10);
                border: 1px solid rgba(238, 107, 107, 0.25);
                color: #F2A8A8;
            }}
            QPushButton[text="Force HIGH BP"] {{
                background: rgba(228, 175, 61, 0.10);
                border: 1px solid rgba(228, 175, 61, 0.25);
                color: #F0D08B;
            }}
            QPushButton[text="Auto / Normal"] {{
                background: rgba(47, 208, 127, 0.10);
                border: 1px solid rgba(47, 208, 127, 0.25);
                color: #B6F0D2;
            }}
            QPushButton[text="Run I2C scan"] {{
                background: rgba(39, 216, 200, 0.10);
                border: 1px solid rgba(39, 216, 200, 0.25);
                color: #A3F2EC;
            }}
            QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
                background: {THEME["panel2"]};
                color: {THEME["text"]};
                border: 1px solid {THEME["border"]};
                border-radius: 10px;
                padding: 8px 10px;
                selection-background-color: {THEME["accent"]};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 28px;
            }}
            QComboBox QAbstractItemView {{
                background: {THEME["panel2"]};
                color: {THEME["text"]};
                selection-background-color: {THEME["accent"]};
                outline: 0;
            }}
            QPlainTextEdit {{
                background: #0f1216;
                color: #d8e1ea;
                border: 1px solid {THEME["border"]};
                border-radius: 14px;
                padding: 12px;
                selection-background-color: {THEME["accent"]};
                font-family: "SF Mono", "JetBrains Mono", "Consolas", monospace;
                font-size: 12px;
            }}
            QProgressBar {{
                background: {THEME["panel2"]};
                border: 1px solid {THEME["border"]};
                border-radius: 8px;
                text-align: center;
                height: 12px;
            }}
            QProgressBar::chunk {{
                border-radius: 8px;
                background: qlineargradient(
                    x1: 0, y1: 0, x2: 1, y2: 0,
                    stop: 0 {THEME["accent2"]},
                    stop: 1 {THEME["accent"]}
                );
            }}
            QSplitter::handle {{
                background: transparent;
            }}
            """
        )

    def append_log(self, text: str):
        self.console.appendPlainText(text)

    def _tick_visuals(self):
        if self.serial_ok and self.latest.get("hr"):
            self.synth.set_bpm(self.latest["hr"])
        self.synth.step()
        x, y = self.synth.data()
        self.wave_curve.setData(x, y)

        # keep the plot styled after themes are set
        self.plot.getAxis("bottom").setPen(pg.mkPen(QColor(THEME["grid"])))
        self.plot.getAxis("left").setPen(pg.mkPen(QColor(THEME["grid"])))
        self.plot.getAxis("bottom").setTextPen(pg.mkPen(QColor(THEME["muted"])))
        self.plot.getAxis("left").setTextPen(pg.mkPen(QColor(THEME["muted"])))

    def _tick_health(self):
        age = time.monotonic() - self.last_packet_at if self.last_packet_at else 999.0
        if not self.serial_ok:
            self.conn_pill.setText("DISCONNECTED")
            self.conn_pill.setStyleSheet(
                f"background: rgba(238, 107, 107, 0.12); color: {THEME['danger']};"
                f" border: 1px solid rgba(238, 107, 107, 0.24); border-radius: 999px; padding: 8px 12px; font-size: 12px; font-weight: 700;"
            )
            self.health_state.setText("Offline")
            self.health_bar.setValue(0)
            self.status_desc.setText("Connect a serial device to begin receiving telemetry.")
            return

        if age < 1.0:
            freshness = 100
            state = "LIVE"
            text = "Telemetry is streaming smoothly."
            color = THEME["success"]
        elif age < 3.0:
            freshness = 70
            state = "STALE"
            text = "Connection is open, but telemetry has slowed down."
            color = THEME["warning"]
        else:
            freshness = 20
            state = "IDLE"
            text = "Connection is open, but no recent telemetry has arrived."
            color = THEME["danger"]

        self.conn_pill.setText("CONNECTED")
        self.conn_pill.setStyleSheet(
            f"background: rgba(60, 198, 255, 0.12); color: {THEME['accent']};"
            f" border: 1px solid rgba(60, 198, 255, 0.28); border-radius: 999px; padding: 8px 12px; font-size: 12px; font-weight: 700;"
        )
        self.health_state.setText(state)
        self.health_state.setStyleSheet(
            f"color: {color}; font-size: 12px; font-weight: 700;"
        )
        self.health_bar.setValue(freshness)
        self.status_desc.setText(text)

    def start_connection(self, port: str, baud: int):
        if self.worker:
            self.disconnect_device()

        self.port = port
        self.baud = baud
        self.port_label.setText(f"Port: {port}")
        self.baud_label.setText(f"Baud: {baud}")

        self.worker = SerialWorker(port, baud)
        self.worker.telemetry.connect(self.on_packet)
        self.worker.raw_line.connect(self.on_raw_line)
        self.worker.status.connect(self.on_status)
        self.worker.disconnected.connect(self.on_disconnected)
        self.worker.start()
        self.serial_ok = True
        self.last_packet_at = time.monotonic()

    def reconnect(self):
        dlg = ConnectionDialog(self)
        dlg.port_combo.setCurrentText(self.port)
        default_idx = dlg.baud_combo.findData(self.baud)
        if default_idx >= 0:
            dlg.baud_combo.setCurrentIndex(default_idx)
        if dlg.exec() == QDialog.Accepted:
            self.start_connection(dlg.selected_port(), dlg.selected_baud())

    def disconnect_device(self):
        if self.worker:
            self.serial_ok = False
            self.worker.stop()
            self.worker.wait(1500)
            self.worker = None
        self._tick_health()

    def send_command(self, cmd: str):
        if not self.worker:
            self.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] Not connected; command '{cmd}' not sent.")
            return
        try:
            self.worker.send_text(cmd)
            self.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] >> {cmd}")
        except Exception as exc:
            QMessageBox.warning(self, "Command failed", str(exc))

    @Slot(dict)
    def on_packet(self, packet: dict):
        self.latest.update(packet)
        self.last_packet_at = time.monotonic()
        self.serial_ok = True

        hr = packet.get("hr")
        sysv = packet.get("sys")
        diav = packet.get("dia")
        spo2 = packet.get("spo2")
        status = packet.get("status", self.latest.get("status", "LIVE"))
        raw = packet.get("raw", "")

        if hr is not None:
            self.card_hr.set_value(f"{hr}")
            self.card_hr.set_subtitle("Measured heart rate")
        else:
            self.card_hr.set_value("--")
            self.card_hr.set_subtitle("Waiting for heart rate")

        if sysv is not None:
            self.card_sys.set_value(f"{sysv}")
            self.card_sys.set_subtitle("Estimated systolic pressure")
        else:
            self.card_sys.set_value("--")
            self.card_sys.set_subtitle("Waiting for systolic")

        if diav is not None:
            self.card_dia.set_value(f"{diav}")
            self.card_dia.set_subtitle("Estimated diastolic pressure")
        else:
            self.card_dia.set_value("--")
            self.card_dia.set_subtitle("Waiting for diastolic")

        if spo2 is not None:
            self.card_spo2.set_value(f"{spo2}")
            self.card_spo2.set_subtitle("Estimated oxygen saturation")
        else:
            self.card_spo2.set_value("--")
            self.card_spo2.set_subtitle("Waiting for SpO2")

        if status == "LOW":
            self.latest["status"] = "LOW"
            self.health_state.setText("LOW BP")
            self.health_state.setStyleSheet(f"color: {THEME['danger']}; font-size: 12px; font-weight: 700;")
        elif status == "HIGH":
            self.latest["status"] = "HIGH"
            self.health_state.setText("HIGH BP")
            self.health_state.setStyleSheet(f"color: {THEME['warning']}; font-size: 12px; font-weight: 700;")
        elif status == "NORMAL":
            self.latest["status"] = "NORMAL"
            self.health_state.setText("NORMAL")
            self.health_state.setStyleSheet(f"color: {THEME['success']}; font-size: 12px; font-weight: 700;")

        hr_txt = f"{hr} BPM" if hr is not None else "-- BPM"
        bp_txt = f"{sysv}/{diav} mmHg" if sysv is not None and diav is not None else "--/-- mmHg"
        spo2_txt = f"{spo2}%" if spo2 is not None else "--%"
        self.append_log(
            f"[{datetime.now().strftime('%H:%M:%S')}] HR={hr_txt}  BP={bp_txt}  SpO2={spo2_txt}  RAW={raw}"
        )

    @Slot(str)
    def on_raw_line(self, line: str):
        self.latest["raw"] = line

    @Slot(str)
    def on_status(self, text: str):
        self.append_log(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")

    @Slot()
    def on_disconnected(self):
        self.serial_ok = False
        self.worker = None
        self._tick_health()

    def closeEvent(self, event):
        self.disconnect_device()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("OpenAI")

    dlg = ConnectionDialog()
    if dlg.exec() != QDialog.Accepted:
        sys.exit(0)

    win = MainWindow(dlg.selected_port(), dlg.selected_baud())
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
