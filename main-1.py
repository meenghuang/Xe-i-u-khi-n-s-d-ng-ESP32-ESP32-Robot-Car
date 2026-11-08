
import network
import socket
import time
import gc
from machine import Pin, PWM

# ==========================================
# 1. CẤU HÌNH WIFI ACCESS POINT
# ==========================================
SSID = "Robot_Car"
PASSWORD = "12345678"

# ==========================================
# 2. CẤU HÌNH GPIO ĐỘNG CƠ (L298N)
# ==========================================
# Động cơ trái
ena = PWM(Pin(16), freq=1000, duty=0)
in1 = Pin(27, Pin.OUT, value=0)
in2 = Pin(26, Pin.OUT, value=0)

# Động cơ phải (Lưu ý: GPIO 12 là Strapping Pin, giữ mức 0 khi boot)
enb = PWM(Pin(17), freq=1000, duty=0)
in3 = Pin(14, Pin.OUT, value=0)
in4 = Pin(12, Pin.OUT, value=0)

# ==========================================
# 3. CẤU HÌNH TỐC ĐỘ & BÙ VÙNG CHẾT (DEADBAND)
# ==========================================
MIN_DUTY = 380        # Ngưỡng PWM tối thiểu để thắng ma sát tĩnh & sụt áp L298N
NORMAL_SPEED = 720    # Tốc độ bình thường (0 - 1023)
BOOST_SPEED = 1023    # Tốc độ tối đa khi nhấn giữ BOOST
DEADZONE = 8          # Vùng chết tâm Joystick (%)
TIMEOUT_MS = 800      # Thời gian tự ngắt an toàn khi mất kết nối (ms)

last_command = time.ticks_ms()

# Đọc sẵn giao diện Web vào RAM để tăng tốc độ phản hồi
try:
    with open("index.html", "rb") as f:
        HTML_CONTENT = f.read()
except Exception as e:
    print("Cảnh báo: Không tìm thấy file index.html!", e)
    HTML_CONTENT = b"\<h1>Missing index.html on ESP32\</h1>"

# ==========================================
# 4. HÀM ĐIỀU KHIỂN ĐỘNG CƠ
# ==========================================
def coast():
    """Thả trôi tự nhiên (khi nhả joystick hoặc mất sóng)"""
    ena.duty(0)
    enb.duty(0)
    in1.value(0)
    in2.value(0)
    in3.value(0)
    in4.value(0)


def active_brake():
    """Phanh gấp điện từ (khóa bánh khi nhấn nút BRAKE)"""
    in1.value(1)
    in2.value(1)
    in3.value(1)
    in4.value(1)
    ena.duty(1023)
    enb.duty(1023)


def map_pwm(val, max_duty):
    """Ánh xạ giá trị (-100 -> 100) sang dải PWM thực tế (MIN_DUTY -> max_duty)"""
    if abs(val) < DEADZONE:
        return 0

    sign = 1 if val > 0 else -1
    norm = (abs(val) - DEADZONE) / (100 - DEADZONE)
    duty = int(MIN_DUTY + norm * (max_duty - MIN_DUTY))

    return sign * min(1023, duty)


def set_motor(left_pwm, right_pwm):
    # Điều khiển chiều quay kênh Trái
    if left_pwm > 0:
        in1.value(1)
        in2.value(0)
    elif left_pwm < 0:
        in1.value(0)
        in2.value(1)
    else:
        in1.value(0)
        in2.value(0)

    # Điều khiển chiều quay kênh Phải
    if right_pwm > 0:
        in3.value(1)
        in4.value(0)
    elif right_pwm < 0:
        in3.value(0)
        in4.value(1)
    else:
        in3.value(0)
        in4.value(0)

    ena.duty(abs(left_pwm))
    enb.duty(abs(right_pwm))


# ==========================================
# 5. XỬ LÝ LỆNH TỪ WEB
# ==========================================
def handle_command(command):
    global last_command

    # Giải mã ký tự URL (%2C -> dấu phẩy) do hàm encodeURIComponent trên JS tạo ra
    command = command.replace("%2C", ",").replace("%2c", ",").strip()

    if command == "brake":
        active_brake()
        last_command = time.ticks_ms()
        return

    if command == "stop":
        coast()
        last_command = time.ticks_ms()
        return

    try:
        parts = command.split(",")

        if len(parts) != 3:
            return

        x = max(-100, min(100, int(parts[0])))
        y = max(-100, min(100, int(parts[1])))
        boost = int(parts[2])

    except ValueError:
        return

    # Bỏ qua nhiễu khi Joystick ở vị trí nghỉ
    if abs(x) < DEADZONE and abs(y) < DEADZONE:
        coast()
        last_command = time.ticks_ms()
        return

    max_speed = BOOST_SPEED if boost == 1 else NORMAL_SPEED

    # Trộn kênh vi sai (Differential Steering)
    # Giảm nhẹ độ nhạy trục X (0.75) để xe cua mượt, không bị văng đầu
    turn = int(x * 0.75)
    raw_left = y + turn
    raw_right = y - turn

    # Chuẩn hóa về thang [-100, 100]
    largest = max(abs(raw_left), abs(raw_right), 100)
    norm_left = (raw_left * 100) / largest
    norm_right = (raw_right * 100) / largest

    # Quy đổi sang xung PWM có bù vùng chết L298N
    pwm_left = map_pwm(norm_left, max_speed)
    pwm_right = map_pwm(norm_right, max_speed)

    set_motor(pwm_left, pwm_right)
    last_command = time.ticks_ms()


# ==========================================
# 6. KHỞI TẠO WIFI & HTTP SERVER
# ==========================================
def start_wifi():
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(
        essid=SSID,
        password=PASSWORD,
        authmode=network.AUTH_WPA_WPA2_PSK
    )

    while not ap.active():
        time.sleep_ms(50)

    print("================================")
    print("ROBOT WIFI STARTED")
    print("SSID:", SSID)
    print("IP:  ", ap.ifconfig()[0])
    print("================================")

    return ap


def send_response(client, body, content_type="text/plain"):
    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: " + content_type + "\r\n"
        "Content-Length: " + str(len(body)) + "\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "Access-Control-Allow-Origin: *\r\n\r\n"
    )

    client.sendall(header.encode() + body)


# ==========================================
# 7. VÒNG LẶP CHÍNH (MAIN LOOP)
# ==========================================
coast()
ap = start_wifi()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(("0.0.0.0", 80))
server.listen(4)
server.settimeout(0.02)  # Timeout ngắn (20ms) để vòng lặp kiểm tra an toàn liên tục

print("Truy cập điều khiển tại: http://192.168.4.1")

loop_count = 0

while True:
    try:
        client, addr = server.accept()

        try:
            client.settimeout(0.15)
            request = client.recv(512).decode("utf-8", "ignore")

            if request:
                first_line = request.split("\r\n", 1)[0]
                parts = first_line.split(" ")

                if len(parts) >= 2:
                    path = parts[1]

                    # Xử lý lệnh điều khiển động cơ
                    if path.startswith("/cmd?v="):
                        cmd_val = path.split("/cmd?v=", 1)[1].split("&")[0]
                        handle_command(cmd_val)
                        send_response(client, b"OK")

                    # Trả về giao diện điều khiển từ RAM
                    elif path == "/" or path.startswith("/index.html"):
                        send_response(
                            client,
                            HTML_CONTENT,
                            "text/html; charset=utf-8"
                        )

                    else:
                        send_response(client, b"Not Found")

        except Exception:
            pass

        finally:
            client.close()

    except OSError:
        # Không có kết nối mới trong 20ms, bỏ qua để chạy tiếp
        pass

    # Tự động dừng xe nếu mất kết nối quá TIMEOUT_MS
    if time.ticks_diff(time.ticks_ms(), last_command) > TIMEOUT_MS:
        coast()

    # Dọn rác bộ nhớ định kỳ tránh lỗi tràn RAM (MemoryError) trên ESP32
    loop_count += 1

    if loop_count >= 200:
        gc.collect()
        loop_count = 0
