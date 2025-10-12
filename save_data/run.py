#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, csv, re, time, argparse, threading, queue, signal
import serial
from statistics import mean

PORT = "/dev/ttyACM0"
FILE = "runlog.csv"

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
    parser = argparse.ArgumentParser(
        description="Sweep HZ: đọc 1 Hz, trung bình 20s, ghi CSV (hz_avg,rpm_avg,flow1_avg,volt1_avg,volt2_avg,analog) rồi mới nhảy HZ."
    )
    parser.add_argument("--port", default=PORT, help="Cổng nối tiếp (/dev/ttyACM0, /dev/ttyUSB0, COM3, ...)")
    parser.add_argument("--baud", type=int, default=115200, help="Baudrate (mặc định 115200)")

    parser.add_argument("--mode", choices=["fixed", "ramp", "sweep"], default="sweep",
                        help="sweep = 0→1→2…; fixed = tần số cố định; ramp = tăng theo thời gian")

    # fixed
    parser.add_argument("--hz", type=int, default=30, help="Tần số đặt khi fixed (0..60)")

    # ramp
    parser.add_argument("--ramp-start", type=int, default=10)
    parser.add_argument("--ramp-stop", type=int, default=60)
    parser.add_argument("--ramp-step", type=int, default=5)
    parser.add_argument("--ramp-interval", type=float, default=10.0, help="Khoảng giữa các lần tăng HZ (giây)")

    # sweep
    parser.add_argument("--sweep-start", type=int, default=0)
    parser.add_argument("--sweep-stop", type=int, default=60)
    parser.add_argument("--sweep-step", type=int, default=1)

    parser.add_argument("--duration", type=float, default=0.0, help="Giới hạn thời lượng tổng (0 = không giới hạn)")

    # đọc/ghi
    parser.add_argument("--sample-rate", type=int, default=1, help="Tần số yêu cầu STATUS (Hz).")
    parser.add_argument("--avg-window", type=float, default=20.0, help="Cửa sổ trung bình (giây).")
    parser.add_argument("--csv", default=FILE, help="Đường dẫn file CSV output")
    args = parser.parse_args()

    # Mở serial
    try:
        ser = serial.Serial(args.port, args.baud, timeout=0.2)
    except Exception as e:
        print(f"❌ Không mở được cổng {args.port}: {e}")
        sys.exit(1)

    line_q = queue.Queue()
    reader = SerialReader(ser, line_q)
    reader.start()

    stop_flag = {"v": False}
    def on_sig(sig, frame):
        stop_flag["v"] = True
    signal.signal(signal.SIGINT, on_sig)
    signal.signal(signal.SIGTERM, on_sig)

    # CSV header: đúng yêu cầu
    first_create = not os.path.exists(args.csv)
    f = open(args.csv, "a", newline="")
    writer = csv.writer(f)
    if first_create:
        writer.writerow(["hz", "rpm", "flowABB", "voltABB", "voltMaf", "analog"])

    wait_banner(line_q, timeout=3.0)

    # Khởi động
    send_cmd(ser, "RESET")
    time.sleep(0.2)
    send_cmd(ser, "RUN")

    status_period = 1.0 / float(max(1, args.sample_rate))
    next_status = time.time()

    last_run = 0
    last_hold = 0

    print("✅ Bắt đầu. Mỗi mức HZ: đọc 1Hz trong 20s → tính trung bình → ghi CSV (hz_avg..analog) → sang HZ kế tiếp.")
    t_end = time.time() + args.duration if args.duration > 0 else None

    try:
        if args.mode == "sweep":
            hz_values = list(range(
                max(0, min(60, args.sweep_start)),
                max(0, min(60, args.sweep_stop)) + 1,
                max(1, args.sweep_step)
            ))

            for target_hz in hz_values:
                if stop_flag["v"]:
                    break
                if t_end and time.time() >= t_end:
                    print("⏱️ Hết thời lượng tổng.")
                    break

                # Đặt HZ
                send_cmd(ser, f"SET_HZ {target_hz}")
                print(f"\n=== 🔹 HZ = {target_hz} ─ BẮT ĐẦU GOM {args.avg_window:.1f}s ===")
                time.sleep(0.3)  # cho hệ ổn định nhẹ

                bucket = []
                t0 = time.time()
                next_status = t0

                while (time.time() - t0) < args.avg_window and not stop_flag["v"]:
                    now = time.time()
                    if now >= next_status:
                        send_cmd(ser, "STATUS")
                        next_status = now + status_period

                    try:
                        line = line_q.get(timeout=0.1)
                    except queue.Empty:
                        continue

                    if line.startswith("__ERR__"):
                        print(f"[SERIAL ERR] {line}")
                        continue
                    if line.startswith("OK") or line.startswith("ERR"):
                        print(f"[CMD] {line}")
                        continue

                    m = STATUS_RE.match(line)
                    if not m:
                        continue

                    hz = int(m.group("hz"))
                    rpm = float(m.group("rpm"))
                    flow1 = float(m.group("flow1"))
                    volt1 = float(m.group("volt1"))
                    flow2 = float(m.group("flow2"))
                    volt2 = float(m.group("volt2"))
                    last_run = int(m.group("run"))
                    last_hold = int(m.group("hold"))

                    if hz == target_hz:
                        bucket.append((rpm, flow1, volt1, flow2, volt2))
                        elapsed = time.time() - t0
                        print(f"[READ] t={elapsed:5.1f}s | hz={hz:02d} rpm={rpm:.1f} | f1={flow1:.3f} v1={volt1:.3f} | f2={flow2:.3f} v2={volt2:.3f}")

                # Trung bình & ghi CSV (đúng 6 cột yêu cầu)
                if bucket:
                    rpms = [x[0] for x in bucket]
                    f1s  = [x[1] for x in bucket]
                    v1s  = [x[2] for x in bucket]
                    f2s  = [x[3] for x in bucket]
                    v2s  = [x[4] for x in bucket]

                    rpm_avg   = round(mean(rpms), 3)
                    flow1_avg = round(mean(f1s) *3.6, 2)
                    volt1_avg = round(mean(v1s), 2)
                    volt2_avg = round(mean(v2s), 2)
                    analog    = round((volt2_avg * 1023.0) / 5.0, 3)  # yêu cầu: analog = volt2_avg * 1023 / 5

                    row = [target_hz, rpm_avg, flow1_avg, volt1_avg, volt2_avg, analog]
                    writer.writerow(row)
                    f.flush()
                    print(f"🧾 [CSV] hz_avg={target_hz} | rpm_avg={rpm_avg} | flow1_avg={flow1_avg} | volt1_avg={volt1_avg} | volt2_avg={volt2_avg} | analog={analog}")
                else:
                    print(f"⚠️ Không thu được mẫu hợp lệ cho HZ={target_hz} trong {args.avg_window:.1f}s")

        elif args.mode == "fixed":
            target_hz = max(0, min(60, args.hz))
            send_cmd(ser, f"SET_HZ {target_hz}")
            print(f"[FIXED] HZ={target_hz}")
            bucket = []
            t0 = time.time()
            while not stop_flag["v"]:
                now = time.time()
                if t_end and now >= t_end:
                    print("⏱️ Hết thời lượng.")
                    break
                if now >= next_status:
                    send_cmd(ser, "STATUS")
                    next_status = now + status_period
                try:
                    line = line_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                m = STATUS_RE.match(line or "")
                if not m:
                    continue
                hz = int(m.group("hz"))
                if hz != target_hz:
                    continue
                rpm = float(m.group("rpm"))
                flow1 = float(m.group("flow1"))
                volt1 = float(m.group("volt1"))
                flow2 = float(m.group("flow2"))
                volt2 = float(m.group("volt2"))
                bucket.append((rpm, flow1, volt1, flow2, volt2))
                print(f"[READ] hz={hz:02d} rpm={rpm:.1f} | f1={flow1:.3f} v1={volt1:.3f} | f2={flow2:.3f} v2={volt2:.3f}")
                if (now - t0) >= args.avg_window and bucket:
                    rpms = [x[0] for x in bucket]
                    f1s  = [x[1] for x in bucket]
                    v1s  = [x[2] for x in bucket]
                    f2s  = [x[3] for x in bucket]
                    v2s  = [x[4] for x in bucket]
                    rpm_avg   = round(mean(rpms), 3)
                    flow1_avg = round(mean(f1s), 6)
                    volt1_avg = round(mean(v1s), 6)
                    volt2_avg = round(mean(v2s), 6)
                    analog    = round((volt2_avg * 1023.0) / 5.0, 3)
                    row = [target_hz, rpm_avg, flow1_avg, volt1_avg, volt2_avg, analog]
                    writer.writerow(row)
                    f.flush()
                    print(f"🧾 [CSV] hz_avg={target_hz} | rpm_avg={rpm_avg} | flow1_avg={flow1_avg} | volt1_avg={volt1_avg} | volt2_avg={volt2_avg} | analog={analog}")
                    bucket = []
                    t0 = now

        else:  # ramp
            target_hz = max(0, min(60, args.ramp_start))
            send_cmd(ser, f"SET_HZ {target_hz}")
            next_ramp = time.time() + args.ramp_interval
            bucket = []
            t0 = time.time()
            while not stop_flag["v"]:
                now = time.time()
                if t_end and now >= t_end:
                    print("⏱️ Hết thời lượng.")
                    break
                if now >= next_status:
                    send_cmd(ser, "STATUS")
                    next_status = now + status_period
                if now >= next_ramp and target_hz < args.ramp_stop:
                    # ghi 1 dòng nếu đủ cửa sổ trước khi tăng
                    if (now - t0) >= args.avg_window and bucket:
                        rpms = [x[0] for x in bucket]
                        f1s  = [x[1] for x in bucket]
                        v1s  = [x[2] for x in bucket]
                        f2s  = [x[3] for x in bucket]
                        v2s  = [x[4] for x in bucket]
                        rpm_avg   = round(mean(rpms), 3)
                        flow1_avg = round(mean(f1s), 6)
                        volt1_avg = round(mean(v1s), 6)
                        volt2_avg = round(mean(v2s), 6)
                        analog    = round((volt2_avg * 1023.0) / 5.0, 3)
                        row = [target_hz, rpm_avg, flow1_avg, volt1_avg, volt2_avg, analog]
                        writer.writerow(row)
                        f.flush()
                        print(f"🧾 [CSV] hz_avg={target_hz} | rpm_avg={rpm_avg} | flow1_avg={flow1_avg} | volt1_avg={volt1_avg} | volt2_avg={volt2_avg} | analog={analog}")
                    # tăng HZ
                    target_hz = min(args.ramp_stop, target_hz + args.ramp_step)
                    send_cmd(ser, f"SET_HZ {target_hz}")
                    print(f"[RAMP] → SET_HZ {target_hz}")
                    bucket = []
                    t0 = now
                    next_ramp = now + args.ramp_interval
                try:
                    line = line_q.get(timeout=0.1)
                except queue.Empty:
                    continue
                m = STATUS_RE.match(line or "")
                if not m:
                    continue
                hz = int(m.group("hz"))
                if hz != target_hz:
                    continue
                rpm = float(m.group("rpm"))
                flow1 = float(m.group("flow1"))
                volt1 = float(m.group("volt1"))
                flow2 = float(m.group("flow2"))
                volt2 = float(m.group("volt2"))
                bucket.append((rpm, flow1, volt1, flow2, volt2))
                print(f"[READ] hz={hz:02d} rpm={rpm:.1f} | f1={flow1:.3f} v1={volt1:.3f} | f2={flow2:.3f} v2={volt2:.3f}")
                if (now - t0) >= args.avg_window and bucket:
                    rpms = [x[0] for x in bucket]
                    f1s  = [x[1] for x in bucket]
                    v1s  = [x[2] for x in bucket]
                    f2s  = [x[3] for x in bucket]
                    v2s  = [x[4] for x in bucket]
                    rpm_avg   = round(mean(rpms), 3)
                    flow1_avg = round(mean(f1s), 6)
                    volt1_avg = round(mean(v1s), 6)
                    volt2_avg = round(mean(v2s), 6)
                    analog    = round((volt2_avg * 1023.0) / 5.0, 3)
                    row = [target_hz, rpm_avg, flow1_avg, volt1_avg, volt2_avg, analog]
                    writer.writerow(row)
                    f.flush()
                    print(f"🧾 [CSV] hz_avg={target_hz} | rpm_avg={rpm_avg} | flow1_avg={flow1_avg} | volt1_avg={volt1_avg} | volt2_avg={volt2_avg} | analog={analog}")
                    bucket = []
                    t0 = now

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

    print(f"\n🏁 STOP. Đã đưa HZ về 0. CSV: {os.path.abspath(args.csv)}")

if __name__ == "__main__":
    main()
