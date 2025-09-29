#!/usr/bin/env python3

import sys
import csv
import serial
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QMessageBox,
    QVBoxLayout, QHBoxLayout, QSplitter
)
from PyQt5.QtGui import QFont, QColor, QPainter, QFontDatabase
from PyQt5.QtCore import QTimer, QPointF, Qt
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QAreaSeries, QValueAxis

MAIN_FONT = "~/.fonts/maf.ttf"  # Đường dẫn font tùy biến của bạn
MAX_VALUE = 120               # Trục Y cho biểu đồ lưu lượng khí nạp (g/s)

class ChartReadData(QMainWindow):
    def __init__(self):
        super().__init__()

        # ====== Font ứng dụng ======
        try:
            font_id = QFontDatabase.addApplicationFont(MAIN_FONT)
            families = QFontDatabase.applicationFontFamilies(font_id)
            font_family = families[0] if families else "Arial"
        except Exception:
            font_family = "Arial"

        # ====== Cửa sổ chính ======
        self.setWindowTitle("Đồ án lưu lượng khí nạp")
        self.resize(1000, 800)

        # ====== Kết nối Serial ======
        try:
            self.serial = serial.Serial('/dev/ttyACM0', 9600, timeout=1)
        except Exception as e:
            self.serial = None
            QMessageBox.warning(
                self, "Cảnh báo",
                f"Không mở được cổng Serial: {e}\nChương trình vẫn chạy chế độ không có dữ liệu."
            )

        # Bộ đếm thời gian theo trục X
        self.x = 0
        self.data1 = []  # (x, y1) – điện áp
        self.data2 = []  # (x, y2) – lưu lượng

        # =====================================================================
        # Biểu đồ 1: ĐIỆN ÁP (LineSeries)
        # =====================================================================
        self.line_series = QLineSeries()
        self.line_series.setName("Dữ liệu điện áp")  # tên hiện ở legend

        self.chart1 = QChart()
        self.chart1.addSeries(self.line_series)
        self.chart1.setTitle("Biểu đồ điện áp cảm biến")
        self.chart1.setTitleFont(QFont(font_family, 10))
        self.chart1.setAnimationOptions(QChart.SeriesAnimations)
        self.chart1.setBackgroundBrush(QColor("white"))

        # Thu nhỏ chữ legend (nơi hiển thị "Dữ liệu điện áp")
        self.chart1.legend().setFont(QFont(font_family, 8))

        self.axis_x1 = QValueAxis()
        self.axis_x1.setLabelFormat("%d")
        self.axis_x1.setRange(0, 50)
        self.axis_x1.setTitleText("Lưu lượng (kg/h)")
        self.axis_x1.setTitleFont(QFont(font_family, 8))

        self.axis_y1 = QValueAxis()
        self.axis_y1.setRange(0, 5)
        self.axis_y1.setTitleText("Điện áp (V)")
        self.axis_y1.setTitleFont(QFont(font_family, 8))

        self.chart1.addAxis(self.axis_x1, Qt.AlignBottom)
        self.chart1.addAxis(self.axis_y1, Qt.AlignLeft)
        self.line_series.attachAxis(self.axis_x1)
        self.line_series.attachAxis(self.axis_y1)

        self.chart_view1 = QChartView(self.chart1)
        self.chart_view1.setRenderHint(QPainter.Antialiasing)

        # =====================================================================
        # Biểu đồ 2: LƯU LƯỢNG KHÍ NẠP (AreaSeries = upper - lower)
        # =====================================================================
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
        self.chart2.setAnimationOptions(QChart.SeriesAnimations)
        self.chart2.setBackgroundBrush(QColor("white"))

        # Thu nhỏ chữ legend (nơi hiển thị "Dữ liệu cảm biến")
        self.chart2.legend().setFont(QFont(font_family, 8))

        self.axis_x2 = QValueAxis()
        self.axis_x2.setTitleText("Time (s)")
        self.axis_x2.setTitleFont(QFont(font_family, 8))
        self.axis_x2.setLabelFormat("%d")
        self.axis_x2.setRange(0, 50)

        self.axis_y2 = QValueAxis()
        self.axis_y2.setTitleText("Lưu lượng khí nạp (g/s)")
        self.axis_y2.setTitleFont(QFont(font_family, 8))
        self.axis_y2.setLabelFormat("%d")
        self.axis_y2.setRange(0, MAX_VALUE)

        self.chart2.addAxis(self.axis_x2, Qt.AlignBottom)
        self.chart2.addAxis(self.axis_y2, Qt.AlignLeft)
        self.area_series.attachAxis(self.axis_x2)
        self.area_series.attachAxis(self.axis_y2)

        self.chart_view2 = QChartView(self.chart2)
        self.chart_view2.setRenderHint(QPainter.Antialiasing)

        # =====================================================================
        # Nút LƯU CSV
        # =====================================================================
        self.save_button = QPushButton("Lưu ra CSV")
        self.save_button.setFont(QFont(font_family, 9))
        self.save_button.setStyleSheet(
            "background-color: #50FA7B; padding: 8px 12px; "
            "border-radius: 10px; font-weight: bold;"
        )
        self.save_button.clicked.connect(self.save_csv)

        # =====================================================================
        # GIAO DIỆN: Hai biểu đồ TRÁI – PHẢI bằng QSplitter
        # =====================================================================
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.chart_view1)
        splitter.addWidget(self.chart_view2)
        splitter.setSizes([500, 500])  # tỉ lệ ban đầu trái/phải

        root_layout = QVBoxLayout()
        root_layout.addWidget(splitter)
        root_layout.addWidget(self.save_button)

        container = QWidget()
        container.setLayout(root_layout)
        container.setStyleSheet("background-color: #282A36;")
        self.setCentralWidget(container)

        # =====================================================================
        # TIMER: cập nhật dữ liệu
        # =====================================================================
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_data)
        self.timer.start(500)  # 500 ms

    def update_data(self):
        """Đọc dữ liệu từ Serial: 'y1,y2' -> cập nhật hai biểu đồ"""
        if not self.serial:
            return

        try:
            line = self.serial.readline().decode('utf-8', errors='ignore').strip()
            print("Data:", line)
            if not line:
                return

            parts = line.split(",")
            if len(parts) != 2:
                return

            y1 = float(parts[0])   # Điện áp (V)
            y2 = float(parts[1])   # Lưu lượng (g/s)

            self.x += 1
            self.data1.append((y2, y1))
            self.data2.append((self.x, y2))

            # Cập nhật biểu đồ 1 (điện áp)
            self.line_series.append(QPointF(y2, y1))

            # Cập nhật biểu đồ 2 (area: upper = y2, lower = 0)
            self.upper_series.append(QPointF(self.x, y2))
            self.lower_series.append(QPointF(self.x, 0))

            # Cuộn trục X để luôn thấy 50 điểm gần nhất
            if self.x > 50:
                self.axis_x1.setRange(self.x - 50, self.x)
                self.axis_x2.setRange(self.x - 50, self.x)

        except Exception as e:
            print("Lỗi khi đọc dữ liệu:", e)

    def save_csv(self):
        """Lưu dữ liệu ra data.csv"""
        try:
            with open('data.csv', 'w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(["Voltage(V)", "Flow(g/s)"])
                for i in range(max(len(self.data1), len(self.data2))):
                    s1 = self.data1[i][1] if i < len(self.data1) else ''
                    s2 = self.data2[i][1] if i < len(self.data2) else ''
                    writer.writerow([s1, s2])
            QMessageBox.information(self, "Lưu thành công", "Dữ liệu đã được lưu vào data.csv")
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể lưu dữ liệu: {e}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ChartReadData()
    window.show()
    sys.exit(app.exec_())
