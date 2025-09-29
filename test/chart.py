#!/usr/bin/env python3
import sys, os, csv, serial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QTabWidget,
    QPushButton, QMessageBox, QSplitter, QLabel
)
from PyQt5.QtGui import QFont, QColor, QPainter, QFontDatabase
from PyQt5.QtCore import Qt, QTimer, QPointF
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QAreaSeries, QValueAxis

MAIN_FONT = "fonts/font.ttf"
MAX_VALUE = 120
CSV_PATH   = "/home/pi/build/main/data.csv"   # đổi nếu cần
SERIAL_DEV = "/dev/ttyACM0"
BAUDRATE   = 9600


# ====================== TAB 1: RealTime ======================
class ChartReadData(QWidget):
    def __init__(self):
        super().__init__()

        # Font
        try:
            font_id = QFontDatabase.addApplicationFont(MAIN_FONT)
            families = QFontDatabase.applicationFontFamilies(font_id)
            font_family = families[0] if families else "Arial"
        except Exception:
            font_family = "Arial"

        # Serial
        try:
            self.serial = serial.Serial(SERIAL_DEV, BAUDRATE, timeout=1)
        except Exception as e:
            self.serial = None
            QMessageBox.warning(self, "Cảnh báo",
                                f"Không mở được cổng Serial {SERIAL_DEV}: {e}\nChạy chế độ không có dữ liệu.")

        # dữ liệu
        self.x = 0
        self.data1 = []   # (flow, volt)
        self.data2 = []   # (t, flow)

        # --- Biểu đồ 1: Voltage theo Flow (Line) ---
        self.line_series = QLineSeries()
        self.line_series.setName("Dữ liệu điện áp")

        self.chart1 = QChart()
        self.chart1.addSeries(self.line_series)
        self.chart1.setTitle("Biểu đồ điện áp cảm biến")
        self.chart1.setTitleFont(QFont(font_family, 10))
        self.chart1.legend().setFont(QFont(font_family, 8))
        self.chart1.setBackgroundBrush(QColor("white"))

        self.axis_x1 = QValueAxis()
        self.axis_x1.setLabelFormat("%d")
        self.axis_x1.setRange(0, 120)
        self.axis_x1.setTitleText("Lưu lượng khí nạp (kg/h)")
        self.chart1.addAxis(self.axis_x1, Qt.AlignBottom)

        self.axis_y1 = QValueAxis()
        self.axis_y1.setRange(0, 5)
        self.axis_y1.setTitleText("Điện áp (V)")
        self.chart1.addAxis(self.axis_y1, Qt.AlignLeft)

        self.line_series.attachAxis(self.axis_x1)
        self.line_series.attachAxis(self.axis_y1)

        self.chart_view1 = QChartView(self.chart1)
        self.chart_view1.setRenderHint(QPainter.Antialiasing)

        # --- Biểu đồ 2: Flow realtime (Area) ---
        self.upper_series = QLineSeries()
        self.lower_series = QLineSeries()
        self.area_series = QAreaSeries(self.upper_series, self.lower_series)
        self.area_series.setName("Dữ liệu cảm biến")
        self.area_series.setBrush(QColor(0, 255, 0, 50))
        self.area_series.setPen(QColor(0, 150, 0))

        self.chart2 = QChart()
        self.chart2.addSeries(self.area_series)
        self.chart2.setTitle("Biểu đồ lưu lượng khí nạp")
        self.chart2.setTitleFont(QFont(font_family, 10))
        self.chart2.legend().setFont(QFont(font_family, 8))
        self.chart2.setBackgroundBrush(QColor("white"))

        self.axis_x2 = QValueAxis()
        self.axis_x2.setTitleText("Time (s)")
        self.axis_x2.setRange(0, 50)
        self.chart2.addAxis(self.axis_x2, Qt.AlignBottom)

        self.axis_y2 = QValueAxis()
        self.axis_y2.setTitleText("Lưu lượng khí nạp (g/s)")
        self.axis_y2.setRange(0, MAX_VALUE)
        self.chart2.addAxis(self.axis_y2, Qt.AlignLeft)

        self.area_series.attachAxis(self.axis_x2)
        self.area_series.attachAxis(self.axis_y2)

        self.chart_view2 = QChartView(self.chart2)
        self.chart_view2.setRenderHint(QPainter.Antialiasing)

        # Nút lưu CSV
        self.save_button = QPushButton("Lưu ra CSV")
        self.save_button.clicked.connect(self.save_csv)

        # Layout
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.chart_view1)
        splitter.addWidget(self.chart_view2)

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(splitter)
        root_layout.addWidget(self.save_button)

        # Timer
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_data)
        self.timer.start(500)

    def update_data(self):
        if not self.serial:
            return
        try:
            line = self.serial.readline().decode('utf-8', errors='ignore').strip()
            if not line:
                return
            parts = line.split(",")
            if len(parts) != 2:
                return

            y1 = float(parts[0])   # Volt
            y2 = float(parts[1])   # Flow

            self.x += 1
            self.data1.append((y2, y1))
            self.data2.append((self.x, y2))

            self.line_series.append(QPointF(y2, y1))
            self.upper_series.append(QPointF(self.x, y2))
            self.lower_series.append(QPointF(self.x, 0))

            if self.x > 120:
                self.axis_x1.setRange(self.x - 120, self.x)
            if self.x > 50:
                self.axis_x2.setRange(self.x - 50, self.x)
        except Exception as e:
            print("Lỗi khi đọc dữ liệu:", e)

    def save_csv(self):
        try:
            os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
            with open(CSV_PATH, 'w', newline='', encoding='utf-8') as f:
                w = csv.writer(f)
                w.writerow(["Voltage(V)", "Flow(g/s)"])
                for i in range(max(len(self.data1), len(self.data2))):
                    s1 = self.data1[i][1] if i < len(self.data1) else ''
                    s2 = self.data2[i][1] if i < len(self.data2) else ''
                    w.writerow([s1, s2])
            QMessageBox.information(self, "OK", f"Đã lưu: {CSV_PATH}")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", str(e))


# ====================== TAB 2: So sánh (CSV + realtime) ======================
class ChartSSData(QWidget):
    def __init__(self):
        super().__init__()

        # Font
        try:
            font_id = QFontDatabase.addApplicationFont(MAIN_FONT)
            families = QFontDatabase.applicationFontFamilies(font_id)
            self.font_family = families[0] if families else "Arial"
        except Exception:
            self.font_family = "Arial"

        # Serial
        try:
            self.serial = serial.Serial(SERIAL_DEV, BAUDRATE, timeout=1)
        except Exception as e:
            self.serial = None
            QMessageBox.warning(self, "Cảnh báo",
                                f"Không mở được cổng Serial {SERIAL_DEV}: {e}\nBiểu đồ realtime sẽ không cập nhật.")

        self.x = 0

        # --- Chart 1: Line từ CSV ---
        self.line_series = QLineSeries()
        self.line_series.setName("Điện áp theo lưu lượng (CSV)")

        self.chart1 = QChart()
        self.chart1.addSeries(self.line_series)
        self.chart1.setTitle("Biểu đồ điện áp cảm biến (từ CSV)")
        self.chart1.setTitleFont(QFont(self.font_family, 10))
        self.chart1.legend().setFont(QFont(self.font_family, 8))
        self.chart1.setBackgroundBrush(QColor("white"))

        self.axis_x1 = QValueAxis(); self.axis_x1.setLabelFormat("%g"); self.axis_x1.setRange(0, 120)
        self.axis_y1 = QValueAxis(); self.axis_y1.setRange(0, 5)
        self.chart1.addAxis(self.axis_x1, Qt.AlignBottom)
        self.chart1.addAxis(self.axis_y1, Qt.AlignLeft)
        self.line_series.attachAxis(self.axis_x1)
        self.line_series.attachAxis(self.axis_y1)
        self.chart_view1 = QChartView(self.chart1); self.chart_view1.setRenderHint(QPainter.Antialiasing)

        # --- Chart 2: Area realtime từ Serial ---
        self.upper_series = QLineSeries()
        self.lower_series = QLineSeries()
        self.area_series = QAreaSeries(self.upper_series, self.lower_series)
        self.area_series.setName("Dữ liệu cảm biến (Serial)")
        self.area_series.setBrush(QColor(0, 255, 0, 50))
        self.area_series.setPen(QColor(0, 150, 0))

        self.chart2 = QChart()
        self.chart2.addSeries(self.area_series)
        self.chart2.setTitle("Biểu đồ lưu lượng khí nạp (realtime)")
        self.chart2.setTitleFont(QFont(self.font_family, 10))
        self.chart2.legend().setFont(QFont(self.font_family, 8))
        self.chart2.setBackgroundBrush(QColor("white"))

        self.axis_x2 = QValueAxis(); self.axis_x2.setTitleText("Time (s)"); self.axis_x2.setRange(0, 50)
        self.axis_y2 = QValueAxis(); self.axis_y2.setTitleText("Lưu lượng khí nạp (g/s)"); self.axis_y2.setRange(0, MAX_VALUE)
        self.chart2.addAxis(self.axis_x2, Qt.AlignBottom)
        self.chart2.addAxis(self.axis_y2, Qt.AlignLeft)
        self.area_series.attachAxis(self.axis_x2)
        self.area_series.attachAxis(self.axis_y2)
        self.chart_view2 = QChartView(self.chart2); self.chart_view2.setRenderHint(QPainter.Antialiasing)

        # Layout đúng cách (KHÔNG dùng setCentralWidget trong QWidget)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.chart_view1)
        splitter.addWidget(self.chart_view2)
        splitter.setSizes([500, 500])

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(splitter)
        self.setStyleSheet("background-color: #282A36;")

        # Nạp CSV cho biểu đồ 1
        self.load_csv_to_linechart(CSV_PATH)

        # Timer realtime cho biểu đồ 2
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_data)
        self.timer.start(500)

    def load_csv_to_linechart(self, path: str):
        try:
            if not os.path.exists(path):
                QMessageBox.critical(self, "Lỗi CSV", f"Không tìm thấy file:\n{path}")
                return

            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                sample = f.read(4096); f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
                except Exception:
                    dialect = csv.excel
                rows = list(csv.reader(f, dialect))

            if not rows:
                QMessageBox.warning(self, "CSV rỗng", "File CSV không có dữ liệu.")
                return

            # Tìm header trong 10 dòng đầu
            header_row_idx = None
            for i, row in enumerate(rows[:10]):
                low = [c.strip().lower() for c in row]
                has_flow = any(k in c for c in low for k in ["lưu lượng", "luu luong", "flow"])
                has_volt = any(k in c for c in low for k in ["volt", "điện áp", "dien ap", "voltage"])
                if has_flow and has_volt:
                    header_row_idx = i; break
            if header_row_idx is None:
                header_row_idx = 2 if len(rows) > 2 else 0  # fallback

            header = [c.strip() for c in rows[header_row_idx]]
            header_low = [c.lower() for c in header]

            def find_idx(keys):
                for j, name in enumerate(header_low):
                    if any(k in name for k in keys):
                        return j
                return None

            idx_flow = find_idx(["lưu lượng", "luu luong", "flow"]) or 0
            idx_volt = find_idx(["volt", "điện áp", "dien ap", "voltage"]) or 1

            xs, ys = [], []
            for r in rows[header_row_idx + 1:]:
                if len(r) <= max(idx_flow, idx_volt): continue
                try:
                    x = float(str(r[idx_flow]).replace(",", "."))
                    y = float(str(r[idx_volt]).replace(",", "."))
                except Exception:
                    continue
                xs.append(x); ys.append(y)

            self.line_series.clear()
            for x, y in zip(xs, ys):
                self.line_series.append(QPointF(x, y))

            if xs and ys:
                xmin, xmax = min(xs), max(xs)
                ymin, ymax = min(ys), max(ys)
                if xmin == xmax: xmin -= 1; xmax += 1
                if ymin == ymax: ymin -= 0.5; ymax += 0.5
                self.axis_x1.setRange(xmin, xmax)
                self.axis_y1.setRange(ymin, ymax)
                self.axis_x1.setTitleText(header[idx_flow] or "Lưu lượng")
                self.axis_y1.setTitleText(header[idx_volt] or "Volt (V)")

        except Exception as e:
            QMessageBox.critical(self, "Lỗi CSV", f"Không thể đọc CSV: {e}")

    def update_data(self):
        if not self.serial:
            return
        try:
            line = self.serial.readline().decode('utf-8', errors='ignore').strip()
            if not line: return
            parts = line.split(",")
            if len(parts) != 2: return

            # y1 = voltage, y2 = flow
            y2 = float(parts[1])

            self.x += 1
            self.upper_series.append(QPointF(self.x, y2))
            self.lower_series.append(QPointF(self.x, 0))
            if self.x > 50:
                self.axis_x2.setRange(self.x - 50, self.x)
        except Exception as e:
            print("Lỗi khi đọc dữ liệu:", e)


# ====================== MAIN ======================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Đồ Án Tốt Nghiệp")
        self.resize(1000, 800)

        tabs = QTabWidget()
        tabs.addTab(ChartReadData(), "Biểu đồ RealTime")
        tabs.addTab(ChartSSData(), "Biểu đồ So sánh")
        self.setCentralWidget(tabs)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MainWindow()
    w.show()
    sys.exit(app.exec_())

