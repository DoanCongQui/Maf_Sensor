#! /usr/bin/env python3
import sys
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
    QHBoxLayout, QGridLayout, QProgressBar, QMessageBox
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont


class MotorPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Điều khiển tốc độ | PyQt5")
        self.resize(560, 360)

        # ====== Trạng thái ======
        self.rpm = 0
        self.RPM_MIN = 0
        self.RPM_MAX = 6000
        self.RPM_STEP = 50
        self.power_on = False
        self.freq_running = True  # True = đang chạy tần số, False = dừng tần số

        # ====== Widget hiển thị RPM ======
        self.lbl_title = QLabel("TỐC ĐỘ (RPM)")
        self.lbl_title.setAlignment(Qt.AlignCenter)
        self.lbl_title.setFont(QFont("Arial", 12, QFont.Bold))

        self.lbl_rpm = QLabel("0")
        self.lbl_rpm.setAlignment(Qt.AlignCenter)
        self.lbl_rpm.setFont(QFont("Consolas", 48, QFont.Bold))
        self.lbl_rpm.setStyleSheet("QLabel { border: 2px solid #888; border-radius: 12px; padding: 8px; }")

        self.bar = QProgressBar()
        self.bar.setRange(self.RPM_MIN, self.RPM_MAX)
        self.bar.setValue(self.rpm)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(16)

        # ====== Các nút điều khiển ======
        self.btn_power = QPushButton("BẬT")
        self.btn_power.setCheckable(True)
        self.btn_power.clicked.connect(self.on_toggle_power)
        self.btn_power.setToolTip("Bật/Tắt nguồn (Phím cách)")

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self.on_reset)
        self.btn_reset.setToolTip("Đưa RPM về 0 (R)")

        self.btn_stop_freq = QPushButton("Dừng tần số")
        self.btn_stop_freq.setCheckable(True)
        self.btn_stop_freq.clicked.connect(self.on_toggle_freq)
        self.btn_stop_freq.setToolTip("Dừng/Chạy tần số (S)")

        self.btn_down = QPushButton("▼ Giảm")
        self.btn_down.clicked.connect(self.decrease_rpm)
        self.btn_down.setAutoRepeat(True)
        self.btn_down.setAutoRepeatInterval(120)
        self.btn_down.setToolTip("Giảm tốc độ (Mũi tên xuống)")

        self.btn_up = QPushButton("▲ Tăng")
        self.btn_up.clicked.connect(self.increase_rpm)
        self.btn_up.setAutoRepeat(True)
        self.btn_up.setAutoRepeatInterval(120)
        self.btn_up.setToolTip("Tăng tốc độ (Mũi tên lên)")

        # ====== Nhãn trạng thái ======
        self.lbl_power = QLabel("Nguồn: TẮT")
        self.lbl_freq = QLabel("Tần số: CHẠY")

        status_font = QFont("Arial", 10, QFont.Bold)
        self.lbl_power.setFont(status_font)
        self.lbl_freq.setFont(status_font)

        # ====== Bố cục ======
        top = QVBoxLayout()
        top.addWidget(self.lbl_title)
        top.addWidget(self.lbl_rpm)
        top.addWidget(self.bar)

        # Hàng nút chính
        grid = QGridLayout()
        grid.addWidget(self.btn_power,    0, 0)
        grid.addWidget(self.btn_reset,    0, 1)
        grid.addWidget(self.btn_stop_freq,0, 2)

        # Hàng tăng/giảm
        h_ud = QHBoxLayout()
        h_ud.addWidget(self.btn_down)
        h_ud.addWidget(self.btn_up)

        # Hàng trạng thái
        h_stat = QHBoxLayout()
        h_stat.addWidget(self.lbl_power, stretch=1)
        h_stat.addWidget(self.lbl_freq,  stretch=1)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addSpacing(8)
        root.addLayout(grid)
        root.addSpacing(6)
        root.addLayout(h_ud)
        root.addSpacing(6)
        root.addLayout(h_stat)

        self.update_ui_state()

    # ====== Cập nhật giao diện & giá trị ======
    def clamp_rpm(self):
        self.rpm = max(self.RPM_MIN, min(self.RPM_MAX, self.rpm))

    def refresh_display(self):
        self.clamp_rpm()
        self.lbl_rpm.setText(f"{self.rpm}")
        self.bar.setValue(self.rpm)

    def update_ui_state(self):
        # Nguồn
        if self.power_on:
            self.lbl_power.setText("Nguồn: BẬT")
            self.btn_power.setText("TẮT")
            self.setEnabled_controls(True)
        else:
            self.lbl_power.setText("Nguồn: TẮT")
            self.btn_power.setText("BẬT")
            # Khi tắt nguồn, đưa RPM về 0 và khoá điều khiển
            self.rpm = 0
            self.setEnabled_controls(False)

        # Tần số
        if self.freq_running:
            self.lbl_freq.setText("Tần số: CHẠY")
            self.btn_stop_freq.setText("Dừng tần số")
        else:
            self.lbl_freq.setText("Tần số: DỪNG")
            self.btn_stop_freq.setText("Chạy tần số")

        self.refresh_display()

    def setEnabled_controls(self, enabled: bool):
        # Khi nguồn OFF => disable tất cả trừ nút BẬT/TẮT
        self.btn_reset.setEnabled(enabled)
        self.btn_stop_freq.setEnabled(enabled)
        # Khi dừng tần số => khoá tăng/giảm
        can_adjust = enabled and self.freq_running
        self.btn_up.setEnabled(can_adjust)
        self.btn_down.setEnabled(can_adjust)

    # ====== Xử lý nút ======
    def on_toggle_power(self, checked: bool):
        self.power_on = checked
        self.update_ui_state()

    def on_reset(self):
        if not self.power_on:
            return
        self.rpm = 0
        self.refresh_display()

    def on_toggle_freq(self, checked: bool):
        if not self.power_on:
            # tự bật lên để tránh nhầm lẫn
            self.btn_stop_freq.setChecked(False)
            QMessageBox.information(self, "Thông báo", "Hãy bật nguồn trước.")
            return
        self.freq_running = not checked  # checked = Dừng → freq_running False
        self.setEnabled_controls(True)    # cập nhật enable/disable
        self.update_ui_state()

    def increase_rpm(self):
        if not (self.power_on and self.freq_running):
            return
        self.rpm += self.RPM_STEP
        self.refresh_display()

    def decrease_rpm(self):
        if not (self.power_on and self.freq_running):
            return
        self.rpm -= self.RPM_STEP
        self.refresh_display()

    # ====== Phím tắt ======
    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self.btn_power.toggle()
            return
        if e.key() == Qt.Key_R:
            self.on_reset()
            return
        if e.key() == Qt.Key_S:
            self.btn_stop_freq.toggle()
            self.on_toggle_freq(self.btn_stop_freq.isChecked())
            return
        if e.key() == Qt.Key_Up:
            self.increase_rpm()
            return
        if e.key() == Qt.Key_Down:
            self.decrease_rpm()
            return
        super().keyPressEvent(e)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MotorPanel()
    w.show()
    sys.exit(app.exec_())
