#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, csv, re, time, argparse, threading, queue, signal
import serial

STATUS_RE = re.compile(
    r"^STATUS\s+hz=(?P<hz>\d+)\s+rpm=(?P<rpm>-?\d+(?:\.\d+)?)\s+run=(?P<run>[01])\s+hold=(?P<hold>[01])\s+"
    r"flow1=(?P<flow1>-?\d+(?:\.\d+)?)\s+volt1=(?P<volt1>-?\d+(?:\.\d+)?)\s+"
    r"flow2=(?P<flow2>-?\d+(?:\.\d+)?)\s+volt2=(?P<volt2>-?\d+(?:\.\d+)?)$"
)

class SerialReader(threading.Thread):
    def __init__(self, ser, line_queue):
        super().__init__(daemon=True)
        self.ser = ser
        self.q = line_queue
        self._run = True

    def stop(self):
        self._run = False

    def run(self):
        buff = bytearray()
        while self._run:
            try:
                b = self.ser.read(1)
                if not b:
                    continue
                if b in b"\r\n":
                    if buff:
                        try:
                            line = buff.decode("utf-8", errors="ignore").strip()
                        finally:
                            buff.clear()
                        if line:
                            self.q.put(line)
                else:
                    buff.extend(b)
            except Exception as e:
                self.q.put(f"__ERR__ {e}")
                time.sleep(0.2)

def send_cmd(ser, cmd):
    ser.write((cmd.strip() + "\n").encode("utf-8"))
    ser.flush()

def wait_banner(q, timeout=5.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            line = q.get(timeout=0.2)
            if "Arduino Ready" in line:
                return True
        except queue.Empty:
            pass
    return False

def graceful_stop(ser):
    try:
        send_cmd(ser, "SET_HZ 0")
        time.sleep(0.1)
        send_cmd(ser, "STOP")
    except Exception:
        pass

def main():
    parser = argparse.ArgumentParser(description="Điều khiển biến tần qua Arduino và ghi log STATUS (mỗi 10s).")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Cổng nối tiếp tới Arduino (/dev/ttyUSB0, /dev/rfcomm0)")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mặc định 115200)")
    parser.add_argument("--mode", choices=["fixed", "ramp"], default="fixed", help="fixed = tần số cố định, ramp = tăng dần")
    parser.add_argument("--hz", type=int, default=30, help="Tần số đặt khi fixed (0..60)")
    parser.add_argument("--ramp-start", type=int, default=10)
    parser.add_argument("--ramp-stop", type=int, default=60)
    parser.add_argument("--ramp-step", type=int, default=5)
    parser.add_argument("--ramp-interval", type=float, default=10.0)
    parser.add_argument("--duration", type=float, default=0.0, help="Thời lượng chạy (0 = vô hạn)")
    parser.add_argument("--csv", default="runlog.csv", help="Đường dẫn file CSV output")
    args = parser.parse_args()

    # Mở cổng serial
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except Exception as e:
        print(f"❌ Không mở được cổng {args.port}: {e}")
        sys.exit(1)

    line_q = queue.Queue()
    reader = SerialReader(ser, line_q)
    reader.start()

    stop_flag = {"v": False}
    def on_sigint(sig, frame):
        stop_flag["v"] = True
    signal.signal(signal.SIGINT, on_sigint)
    signal.signal(signal.SIGTERM, on_sigint)

    # CSV (không có cột thời gian)
    first_create = not os.path.exists(args.csv)
    f = open(args.csv, "a", newline="")
    writer = csv.writer(f)
    if first_create:
        writer.writerow(["hz", "rpm", "flow1", "volt1", "flow2", "volt2"])

    wait_banner(line_q, timeout=3.0)

    # Khởi động
    send_cmd(ser, "RESET")
    time.sleep(0.2)
    send_cmd(ser, "RUN")

    if args.mode == "fixed":
        target_hz = max(0, min(60, args.hz))
    else:
        target_hz = max(0, min(60, args.ramp_start))
    send_cmd(ser, f"SET_HZ {target_hz}")

    next_status = time.time()
    next_ramp = time.time() + (args.ramp_interval if args.mode == "ramp" else 1e9)
    t_end = time.time() + args.duration if args.duration > 0 else None

    print("✅ Bắt đầu chạy (đọc mỗi 10 giây). Nhấn Ctrl+C để dừng an toàn…")

    try:
        while not stop_flag["v"]:
            now = time.time()

            # Gửi STATUS mỗi 10 giây
            if now >= next_status:
                send_cmd(ser, "STATUS")
                next_status = now + 10.0  # 10 giây

            # Ramp nếu cần
            if args.mode == "ramp" and now >= next_ramp:
                if target_hz < args.ramp_stop:
                    target_hz = min(args.ramp_stop, target_hz + args.ramp_step)
                    send_cmd(ser, f"SET_HZ {target_hz}")
                next_ramp = now + args.ramp_interval

            # Đọc phản hồi
            try:
                line = line_q.get(timeout=0.1)
            except queue.Empty:
                line = None

            if line:
                if line.startswith("__ERR__"):
                    print(f"[SERIAL ERR] {line}")
                elif line.startswith("OK") or line.startswith("ERR"):
                    print(f"[CMD] {line}")
                else:
                    m = STATUS_RE.match(line)
                    if m:
                        hz = int(m.group("hz"))
                        rpm = float(m.group("rpm"))
                        flow1 = float(m.group("flow1"))
                        volt1 = float(m.group("volt1"))
                        flow2 = float(m.group("flow2"))
                        volt2 = float(m.group("volt2"))
                        writer.writerow([hz, rpm, flow1, volt1, flow2, volt2])
                        f.flush()
                        print(f"[LOG] hz={hz} rpm={rpm} f1={flow1} v1={volt1} f2={flow2} v2={volt2}")

            # if t_end and now >= t_end:
            #     print("⏱️ Hết thời lượng, dừng an toàn…")
            #     break

    finally:
        try:
            graceful_stop(ser)
        finally:
            reader.stop()
            time.sleep(0.2)
            try:
                ser.close()
            except Exception:
                pass
            f.close()

    print(f"🧾 Đã ghi log vào: {os.path.abspath(args.csv)}")
    print("🏁 Đã STOP và đưa tần số về 0 Hz.")

if __name__ == "__main__":
    main()
