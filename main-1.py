
import network
import socket
import time
from machine import Pin, PWM

# ==========================================
# 1. WIFI CONFIGURATION
# ==========================================

SSID = "Robot_Car"
PASSWORD = "12345678"

# ==========================================
# 2. MOTOR GPIO CONFIGURATION
# Theo cach dau day cua ban
# ==========================================

# LEFT MOTOR
ena = PWM(Pin(16), freq=1000, duty=0)
in1 = Pin(27, Pin.OUT)
in2 = Pin(26, Pin.OUT)

# RIGHT MOTOR
enb = PWM(Pin(17), freq=1000, duty=0)
in3 = Pin(14, Pin.OUT)
in4 = Pin(12, Pin.OUT)

# ==========================================
# 3. SPEED CONFIGURATION
# ==========================================

NORMAL_SPEED = 550
BOOST_SPEED = 800

TIMEOUT_MS = 700

last_command = time.ticks_ms()

# ==========================================
# 4. MOTOR CONTROL
# ==========================================

def stop():
    ena.duty(0)
    enb.duty(0)

    in1.value(0)
    in2.value(0)
    in3.value(0)
    in4.value(0)


def set_motor(left, right):

    left = max(-1023, min(1023, int(left)))
    right = max(-1023, min(1023, int(right)))

    # LEFT MOTOR
    if left > 0:
        in1.value(1)
        in2.value(0)

    elif left < 0:
        in1.value(0)
        in2.value(1)

    else:
        in1.value(0)
        in2.value(0)

    # RIGHT MOTOR
    if right > 0:
        in3.value(1)
        in4.value(0)

    elif right < 0:
        in3.value(0)
        in4.value(1)

    else:
        in3.value(0)
        in4.value(0)

    ena.duty(abs(left))
    enb.duty(abs(right))


# ==========================================
# 5. COMMAND PROCESSING
# ==========================================

def handle_command(command):

    global last_command

    if command == "brake" or command == "stop":
        stop()
        last_command = time.ticks_ms()
        return

    try:
        parts = command.split(",")

        if len(parts) != 3:
            return

        x = int(parts[0])
        y = int(parts[1])
        boost = int(parts[2])

        if boost not in (0, 1):
            return

        x = max(-100, min(100, x))
        y = max(-100, min(100, y))

    except:
        return

    # Chon toc do
    speed = BOOST_SPEED if boost else NORMAL_SPEED

    # Differential steering
    left = y + x
    right = y - x

    # Chuan hoa toc do
    largest = max(abs(left), abs(right), 100)

    left = int(left * speed / largest)
    right = int(right * speed / largest)

    set_motor(left, right)

    last_command = time.ticks_ms()


# ==========================================
# 6. WIFI ACCESS POINT
# ==========================================

def start_wifi():

    ap = network.WLAN(network.AP_IF)

    ap.active(True)

    ap.config(
        essid=SSID,
        password=PASSWORD
    )

    while not ap.active():
        time.sleep_ms(100)

    print("================================")
    print("ROBOT WIFI STARTED")
    print("SSID:", SSID)
    print("IP:", ap.ifconfig()[0])
    print("================================")

    return ap


# ==========================================
# 7. HTTP RESPONSE
# ==========================================

def send_response(client, body, content_type):

    header = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: " + content_type + "\r\n"
        "Cache-Control: no-store\r\n"
        "Connection: close\r\n"
        "Access-Control-Allow-Origin: *\r\n"
        "\r\n"
    )

    client.send(header.encode())
    client.send(body)


# ==========================================
# 8. START ROBOT
# ==========================================

stop()

ap = start_wifi()

server = socket.socket()

server.setsockopt(
    socket.SOL_SOCKET,
    socket.SO_REUSEADDR,
    1
)

server.bind(("0.0.0.0", 80))
server.listen(2)
server.settimeout(0.05)

print("Open: http://192.168.4.1")


# ==========================================
# 9. MAIN LOOP
# ==========================================

while True:

    try:
        client, address = server.accept()

        try:
            client.settimeout(0.3)

            request = client.recv(1024).decode()

            first_line = request.split("\r\n")[0]
            parts = first_line.split(" ")

            if len(parts) < 2:
                client.close()
                continue

            path = parts[1]

            # --------------------------
            # RECEIVE MOTOR COMMAND
            # --------------------------

            if path.startswith("/cmd?"):

                query = path.split("?", 1)[1]

                params = {}

                for item in query.split("&"):

                    if "=" in item:

                        key, value = item.split("=", 1)
                        params[key] = value

                command = params.get("v", "")

                handle_command(command)

                send_response(
                    client,
                    b"OK",
                    "text/plain"
                )

            # --------------------------
            # SEND WEB INTERFACE
            # --------------------------

            elif path == "/" or path.startswith("/index.html"):

                with open("index.html", "rb") as file:
                    html = file.read()

                send_response(
                    client,
                    html,
                    "text/html; charset=utf-8"
                )

            else:

                send_response(
                    client,
                    b"Not found",
                    "text/plain"
                )

        except Exception as error:

            print("Client error:", error)

        finally:

            try:
                client.close()
            except:
                pass

    except OSError:
        pass

    # --------------------------
    # SAFETY TIMEOUT
    # --------------------------

    if time.ticks_diff(
        time.ticks_ms(),
        last_command
    ) > TIMEOUT_MS:

        stop()

    time.sleep_ms(5)
