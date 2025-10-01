#! /usr/bin/env python3
import sys
import argparse
import re
import time

from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QLabel, QVBoxLayout,
    QHBoxLayout, QGridLayout, QProgressBar, QMessageBox, QTextEdit, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt5.QtGui import QFont

import serial
import serial.tools.list_ports


# ====== Serial background reader ======
class SerialReader(QThread):
    line_received = pyqtSignal(str)
    error_signal  = pyqtSignal(str)

    def __init__(self, ser: serial.Serial):
        super().__init__()
        self.ser = ser
        self._running = True

    def run(self):
        try:
            while self._running and self.ser.is_open:
                try:
                    line = self.ser.readline().decode(errors="ignore").strip()
                    if line:
                        self.line_received.emit(line)
                except Exception as e:
                    self.error_signal.emit(f"Reader error: {e}")
                    time.sleep(0.1)
        except Exception as e:
            self.error_signal.emit(f"Thread crashed: {e}")

    def stop(self):
        self._running = False


class MotorPanel(QWidget):
    # 50 Hz ~ 2800 RPM => ~56 RPM/Hz (đặt 50 cho an toàn)
    RPM_PER_HZ = 46
    HZ_MIN = 0
    HZ_MAX = 60

    def __init__(self, ser: serial.Serial, port_name: str):
        super().__init__()
        self.ser = ser
        self.port_name = port_name

        self.setWindowTitle(f"Điều khiển tốc độ | PyQt5 (Port: {self.port_name})")
        self.resize(760, 520)

        # ====== Trạng thái (đồng bộ từ Arduino) ======
        self.hz = 0
        self.rpm = 0
        self.flow = 0.0   # Lưu lượng
        self.volt = 0.0   # Điện áp
        self.power_on = False     # run=1
        self.freq_running = True  # hold=0

        # ====== Giới hạn hiển thị RPM ======
        self.RPM_MIN = 0
        self.RPM_MAX = 2760
        self.RPM_STEP = 46

        # ====== Style chung ======
        self.setStyleSheet("""
        QLabel.title { font-weight: 700; }
        QLabel.kpi {
            border: 2px solid #888; border-radius: 12px; padding: 8px;
        }
        QLabel.badge {
            color: white; padding: 6px 12px; border-radius: 10px; font-weight: 700;
        }
        QPushButton {
            font-size: 16px; padding: 10px 16px; min-height: 44px;
        }
        QProgressBar { border-radius: 6px; height: 16px; }
        QTextEdit { background:#0b0b0b; color:#d0f0d0; font-family: Consolas, monospace; }
        """)

        # ====== Khối KPI trái (RPM + Lưu lượng) ======
        left_col = QVBoxLayout()
        lbl_rpm_title = QLabel("TỐC ĐỘ (RPM)")
        lbl_rpm_title.setObjectName("rpm_title")
        lbl_rpm_title.setProperty("class", "title")
        lbl_rpm_title.setAlignment(Qt.AlignCenter)
        lbl_rpm_title.setFont(QFont("Arial", 12, QFont.Bold))

        self.lbl_rpm = QLabel("0")
        self.lbl_rpm.setAlignment(Qt.AlignCenter)
        self.lbl_rpm.setFont(QFont("Consolas", 48, QFont.Bold))
        self.lbl_rpm.setProperty("class", "kpi")

        self.bar = QProgressBar()
        self.bar.setRange(self.RPM_MIN, self.RPM_MAX)
        self.bar.setValue(self.rpm)
        self.bar.setTextVisible(False)

        # Lưu lượng dưới RPM
        lbl_flow_title = QLabel("Lưu lượng")
        lbl_flow_title.setAlignment(Qt.AlignCenter)
        lbl_flow_title.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_flow = QLabel("--")
        self.lbl_flow.setAlignment(Qt.AlignCenter)
        self.lbl_flow.setFont(QFont("Consolas", 24, QFont.Bold))
        self.lbl_flow.setProperty("class", "kpi")

        left_col.addWidget(lbl_rpm_title)
        left_col.addWidget(self.lbl_rpm)
        left_col.addSpacing(8)
        left_col.addWidget(self.bar)
        left_col.addSpacing(12)
        left_col.addWidget(lbl_flow_title)
        left_col.addWidget(self.lbl_flow)

        # ====== Khối KPI phải (Hz + Điện áp) ======
        right_col = QVBoxLayout()
        lbl_hz_title = QLabel("TẦN SỐ (Hz)")
        lbl_hz_title.setAlignment(Qt.AlignCenter)
        lbl_hz_title.setFont(QFont("Arial", 12, QFont.Bold))

        self.lbl_hz = QLabel("0")
        self.lbl_hz.setAlignment(Qt.AlignCenter)
        self.lbl_hz.setFont(QFont("Consolas", 48, QFont.Bold))
        self.lbl_hz.setProperty("class", "kpi")

        # Điện áp dưới Hz
        lbl_volt_title = QLabel("Điện áp")
        lbl_volt_title.setAlignment(Qt.AlignCenter)
        lbl_volt_title.setFont(QFont("Arial", 11, QFont.Bold))
        self.lbl_volt = QLabel("--")
        self.lbl_volt.setAlignment(Qt.AlignCenter)
        self.lbl_volt.setFont(QFont("Consolas", 24, QFont.Bold))
        self.lbl_volt.setProperty("class", "kpi")

        right_col.addWidget(lbl_hz_title)
        right_col.addWidget(self.lbl_hz)
        right_col.addSpacing(8)
        # có thể thêm 1 progressbar Hz nếu muốn, hiện tại theo yêu cầu chỉ hiển thị số
        right_col.addSpacing(24)
        right_col.addWidget(lbl_volt_title)
        right_col.addWidget(self.lbl_volt)

        # ====== Hai cột KPI đặt cạnh nhau ======
        kpi_row = QHBoxLayout()
        kpi_row.addLayout(left_col, stretch=1)
        # vạch chia
        vline = QFrame()
        vline.setFrameShape(QFrame.VLine)
        vline.setFrameShadow(QFrame.Sunken)
        kpi_row.addWidget(vline)
        kpi_row.addLayout(right_col, stretch=1)

        # ====== Nút điều khiển (to hơn) ======
        self.btn_power = QPushButton("BẬT")
        self.btn_power.setCheckable(True)
        self.btn_power.clicked.connect(self.on_toggle_power)
        self.btn_power.setToolTip("Bật/Tắt RUN (Phím cách)")

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self.on_reset)
        self.btn_reset.setToolTip("Đưa tần số về 0 Hz (R)")

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

        grid = QGridLayout()
        grid.addWidget(self.btn_power,     0, 0)
        grid.addWidget(self.btn_reset,     0, 1)
        grid.addWidget(self.btn_stop_freq, 0, 2)

        h_ud = QHBoxLayout()
        h_ud.addWidget(self.btn_down)
        h_ud.addWidget(self.btn_up)

        # ====== Badge trạng thái kiểu status ======
        self.lbl_power = QLabel("Nguồn: TẮT")
        self.lbl_power.setProperty("class", "badge")
        self.lbl_freq = QLabel("Tần số: CHẠY")
        self.lbl_freq.setProperty("class", "badge")

        stat_row = QHBoxLayout()
        stat_row.addWidget(self.lbl_power, stretch=1, alignment=Qt.AlignLeft)
        stat_row.addWidget(self.lbl_freq,  stretch=1, alignment=Qt.AlignRight)

        # ====== Log Serial ======
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFixedHeight(160)

        # ====== Root layout ======
        root = QVBoxLayout(self)
        root.addLayout(kpi_row)
        root.addSpacing(10)
        root.addLayout(grid)
        root.addSpacing(6)
        root.addLayout(h_ud)
        root.addSpacing(8)
        root.addLayout(stat_row)
        root.addSpacing(8)
        root.addWidget(QLabel("Serial log:"))
        root.addWidget(self.log)

        self.update_ui_state()

        # ====== Serial reader thread ======
        self.reader = SerialReader(self.ser)
        self.reader.line_received.connect(self.on_serial_line)
        self.reader.error_signal.connect(self.on_serial_error)
        self.reader.start()

        # ====== Timer: hỏi STATUS định kỳ ======
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.request_status)
        self.status_timer.start(800)  # ms

    # ====== Serial helpers ======
    def send_cmd(self, cmd: str):
        try:
            if not cmd.endswith("\n"):
                cmd += "\n"
            self.ser.write(cmd.encode())
            self.ser.flush()
            self.append_log(f">>> {cmd.strip()}")
        except Exception as e:
            self.append_log(f"[ERR] send_cmd: {e}")

    def request_status(self):
        self.send_cmd("STATUS")

    def append_log(self, text: str):
        self.log.append(text)
        self.log.moveCursor(self.log.textCursor().End)

    # ====== Parse STATUS & các OK/ERR ======
    def on_serial_line(self, line: str):
        self.append_log(f"{line}")
        # Parse STATUS hz=.. rpm=.. run=.. hold=.. [flow=..] [volt=..]
        if line.startswith("STATUS"):
            m_hz   = re.search(r"hz=(\d+)", line)
            m_rpm  = re.search(r"rpm=(-?\d+)", line)
            m_run  = re.search(r"run=(0|1)", line)
            m_hold = re.search(r"hold=(0|1)", line)
            m_flow = re.search(r"flow=([0-9]+(?:\.[0-9]+)?)", line)
            m_volt = re.search(r"volt=([0-9]+(?:\.[0-9]+)?)", line)

            if m_hz:
                self.hz = int(m_hz.group(1))
            if m_rpm:
                self.rpm = self.hz * self.RPM_PER_HZ
            else:
                self.rpm = self.hz * self.RPM_PER_HZ

            if m_flow:
                self.flow = float(m_flow.group(1))
            else:
                # fallback: nếu không có flow, để "--"
                pass

            if m_volt:
                self.volt = float(m_volt.group(1))
            else:
                # fallback: nếu không có volt, để "--"
                pass

            if m_run:
                self.power_on = (m_run.group(1) == "1")
                self.btn_power.blockSignals(True)
                self.btn_power.setChecked(self.power_on)
                self.btn_power.blockSignals(False)

            if m_hold:
                self.freq_running = (m_hold.group(1) == "0")
                self.btn_stop_freq.blockSignals(True)
                self.btn_stop_freq.setChecked(not self.freq_running)
                self.btn_stop_freq.blockSignals(False)

            self.update_ui_state()

    def on_serial_error(self, msg: str):
        self.append_log(f"[SERIAL ERROR] {msg}")

    # ====== UI helpers ======
    def clamp_rpm(self):
        self.rpm = max(self.RPM_MIN, min(self.RPM_MAX, self.rpm))

    def refresh_display(self):
        self.clamp_rpm()
        self.lbl_rpm.setText(f"{self.rpm}")
        self.bar.setValue(self.rpm)
        self.lbl_hz.setText(f"{self.hz}")
        # Hiển thị flow/volt nếu có, ngược lại là "--"
        self.lbl_flow.setText(f"{self.flow:.1f}" if self.flow else "--")
        self.lbl_volt.setText(f"{self.volt:.1f} V" if self.volt else "--")

    def style_status_badges(self):
        # power_on: xanh lá vs đỏ
        if self.power_on:
            self.lbl_power.setText("Nguồn: BẬT")
            self.lbl_power.setStyleSheet("QLabel { background:#1f9d55; }")  # green
            self.btn_power.setText("TẮT")
        else:
            self.lbl_power.setText("Nguồn: TẮT")
            self.lbl_power.setStyleSheet("QLabel { background:#d64545; }")  # red
            self.btn_power.setText("BẬT")

        # freq_running: xanh dương vs cam
        if self.freq_running:
            self.lbl_freq.setText("Tần số: CHẠY")
            self.lbl_freq.setStyleSheet("QLabel { background:#2563eb; }")  # blue
            self.btn_stop_freq.setText("Dừng tần số")
        else:
            self.lbl_freq.setText("Tần số: DỪNG")
            self.lbl_freq.setStyleSheet("QLabel { background:#f59e0b; }")  # amber
            self.btn_stop_freq.setText("Chạy tần số")

    def update_ui_state(self):
        self.setEnabled_controls(self.power_on)
        self.style_status_badges()
        self.refresh_display()

    def setEnabled_controls(self, enabled: bool):
        self.btn_reset.setEnabled(enabled)
        self.btn_stop_freq.setEnabled(enabled)
        can_adjust = enabled and self.freq_running
        self.btn_up.setEnabled(can_adjust)
        self.btn_down.setEnabled(can_adjust)

    # ====== Xử lý nút ======
    def on_toggle_power(self, checked: bool):
        self.power_on = checked
        if self.power_on:
            self.send_cmd("RUN")
        else:
            self.send_cmd("STOP")
            self.hz = 0
            self.rpm = 0
        self.update_ui_state()

    def on_reset(self):
        if not self.power_on:
            return
        self.send_cmd("RESET")
        self.hz = 0
        self.rpm = 0
        self.refresh_display()

    def on_toggle_freq(self, checked: bool):
        if not self.power_on:
            self.btn_stop_freq.setChecked(False)
            QMessageBox.information(self, "Thông báo", "Hãy bật nguồn trước.")
            return
        if checked:
            self.send_cmd("HOLD_STOP ON")
            self.freq_running = False
        else:
            self.send_cmd("HOLD_STOP OFF")
            self.freq_running = True
        self.update_ui_state()

    def rpm_to_hz(self, rpm_val: int) -> int:
        hz = round(rpm_val / self.RPM_PER_HZ)
        if hz < self.HZ_MIN: hz = self.HZ_MIN
        if hz > self.HZ_MAX: hz = self.HZ_MAX
        return hz

    def increase_rpm(self):
        if not (self.power_on and self.freq_running):
            return
        self.rpm += self.RPM_STEP
        hz = self.rpm_to_hz(self.rpm)
        self.hz = hz
        self.send_cmd(f"SET_HZ {hz}")
        self.refresh_display()

    def decrease_rpm(self):
        if not (self.power_on and self.freq_running):
            return
        self.rpm -= self.RPM_STEP
        hz = self.rpm_to_hz(self.rpm)
        self.hz = hz
        self.send_cmd(f"SET_HZ {hz}")
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

    def closeEvent(self, event):
        try:
            self.reader.stop()
            self.reader.wait(500)
        except:
            pass
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except:
            pass
        event.accept()


def open_serial(port: str, baud: int = 115200, timeout: float = 1.0) -> serial.Serial:
    return serial.Serial(port, baudrate=baud, timeout=timeout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", help="Cổng serial: COMx hoặc /dev/ttyACM0")
    ap.add_argument("--baud", type=int, default=115200)
    args = ap.parse_args()

    # Nếu không chỉ định --port, thử autodetect 1 vài cổng Arduino
    port = args.port
    if not port:
        candidates = []
        for p in serial.tools.list_ports.comports():
            name = p.device
            if ("ACM" in name) or ("USB" in name) or ("COM" in name):
                candidates.append(name)
        if candidates:
            port = candidates[0]
        else:
            print("Không tìm thấy cổng serial. Hãy dùng --port COM3 hoặc /dev/ttyACM0")
            sys.exit(1)

    try:
        ser = open_serial(port, args.baud, timeout=1.0)
    except Exception as e:
        print(f"Không mở được cổng {port}: {e}")
        sys.exit(1)

    app = QApplication(sys.argv)
    w = MotorPanel(ser, port)
    w.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

