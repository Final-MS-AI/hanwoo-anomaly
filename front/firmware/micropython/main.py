import gc
import socket
import time
import _thread

import dht
import network
import ujson
from machine import ADC, Pin

try:
    import requests
except ImportError:
    import urequests as requests

from config import (
    API_BASE_URL,
    DEVICE_ID,
    DEVICE_SECRET,
    WIFI_PASSWORD,
    WIFI_SSID,
)


try:
    socket.setdefaulttimeout(3)
except AttributeError:
    pass


DHT_PIN = 32
GAS_PIN = 35
MOTOR_PIN_NUMBERS = (33, 25, 26, 27)
FIRMWARE_VERSION = "cowow-micropython-2.4.0"

COMMAND_INTERVAL_MS = 200
HEARTBEAT_INTERVAL_MS = 20000
SENSOR_INTERVAL_MS = 30000
WIFI_RETRY_INTERVAL_MS = 10000

MOTOR_STEP_DELAYS_US = {
    1: 4000,
    2: 2500,
    3: 1500,
}

FULL_STEP_SEQUENCE = (
    (1, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 1),
    (1, 0, 0, 1),
)

dht_sensor = dht.DHT11(Pin(DHT_PIN, Pin.IN, Pin.PULL_UP))
gas_sensor = ADC(Pin(GAS_PIN))
gas_sensor.atten(ADC.ATTN_11DB)
gas_sensor.width(ADC.WIDTH_12BIT)
motor_pins = [Pin(number, Pin.OUT) for number in MOTOR_PIN_NUMBERS]

wlan = network.WLAN(network.STA_IF)
wlan.active(True)

fan_level = 0
motor_step_index = 0
last_command_at = 0
last_heartbeat_at = 0
last_sensor_at = 0
last_wifi_attempt_at = 0
temperature = None
humidity = None
air_quality = None


def close_response(response):
    if response is not None:
        try:
            response.close()
        except Exception:
            pass
    gc.collect()


def request_headers():
    return {
        "X-Device-Secret": DEVICE_SECRET,
        "Content-Type": "application/json",
        "Connection": "close",
    }


def get_wifi_rssi():
    try:
        return wlan.status("rssi")
    except Exception:
        return None


def connect_wifi():
    global last_wifi_attempt_at

    if wlan.isconnected():
        return True

    now = time.ticks_ms()
    if (
        last_wifi_attempt_at
        and time.ticks_diff(now, last_wifi_attempt_at)
        < WIFI_RETRY_INTERVAL_MS
    ):
        return False

    last_wifi_attempt_at = now
    print("Wi-Fi 연결 시도:", WIFI_SSID)

    try:
        wlan.disconnect()
    except Exception:
        pass

    time.sleep_ms(200)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    started_at = time.ticks_ms()

    while not wlan.isconnected():
        if time.ticks_diff(time.ticks_ms(), started_at) > 20000:
            print("Wi-Fi 연결 시간 초과")
            return False
        time.sleep_ms(500)

    print("Wi-Fi 연결 완료")
    print("네트워크:", wlan.ifconfig())
    print("신호 세기:", get_wifi_rssi())
    return True


def apply_motor_step(sequence):
    for pin, value in zip(motor_pins, sequence):
        pin.value(value)


def release_motor():
    for pin in motor_pins:
        pin.value(0)


def set_fan_level(level):
    global fan_level

    try:
        level = int(level)
    except (TypeError, ValueError):
        level = 0

    fan_level = max(0, min(3, level))
    print(
        "환기팬 단계:",
        fan_level,
        "수신 시간:",
        time.ticks_ms(),
    )

    if fan_level == 0:
        print("스텝모터 정지")
    else:
        print("스텝모터 회전:", fan_level, "단계")


def motor_worker():
    global motor_step_index

    print("모터 제어 스레드 시작")
    released = False

    while True:
        level = fan_level

        if level == 0:
            if not released:
                release_motor()
                released = True
            time.sleep_ms(20)
            continue

        released = False
        apply_motor_step(FULL_STEP_SEQUENCE[motor_step_index])
        motor_step_index = (motor_step_index + 1) % len(FULL_STEP_SEQUENCE)
        time.sleep_us(MOTOR_STEP_DELAYS_US[level])


def measure_dht11():
    global temperature, humidity

    try:
        dht_sensor.measure()
        temperature = dht_sensor.temperature()
        humidity = dht_sensor.humidity()
        print("DHT11:", temperature, "°C,", humidity, "%")
        return True
    except Exception as error:
        print("DHT11 측정 오류:", repr(error))
        return False


def measure_air_quality():
    global air_quality

    try:
        samples = 10
        total = 0
        for _ in range(samples):
            total += gas_sensor.read()
            time.sleep_ms(20)

        raw = total // samples
        air_quality = round(raw * 100 / 4095, 1)
        print("Air quality:", air_quality, "% (raw:", raw, ")")
        return True
    except Exception as error:
        print("Gas sensor error:", repr(error))
        return False


def send_heartbeat():
    if not wlan.isconnected():
        return

    url = API_BASE_URL + "/devices/" + DEVICE_ID + "/heartbeat"
    body = ujson.dumps(
        {
            "firmwareVersion": FIRMWARE_VERSION,
            "wifiRssi": get_wifi_rssi(),
        }
    )
    response = None

    try:
        response = requests.post(
            url,
            headers=request_headers(),
            data=body,
        )
        if response.status_code != 200:
            print("Heartbeat HTTP:", response.status_code)
            print(response.text)
    except Exception as error:
        print("Heartbeat 오류:", repr(error))
    finally:
        close_response(response)


def send_telemetry():
    if not wlan.isconnected() or temperature is None or humidity is None:
        return

    url = API_BASE_URL + "/devices/" + DEVICE_ID + "/telemetry"
    body = ujson.dumps(
        {
            "temperature": temperature,
            "humidity": humidity,
            "airQuality": air_quality,
        }
    )
    response = None

    try:
        response = requests.post(
            url,
            headers=request_headers(),
            data=body,
        )
        if response.status_code != 200:
            print("Telemetry HTTP:", response.status_code)
            print(response.text)
    except Exception as error:
        print("Telemetry 오류:", repr(error))
    finally:
        close_response(response)


def poll_command():
    if not wlan.isconnected():
        return

    url = (
        API_BASE_URL
        + "/devices/"
        + DEVICE_ID
        + "/commands/pending"
    )
    response = None

    try:
        response = requests.get(url, headers=request_headers())
        if response.status_code != 200:
            print("명령 조회 HTTP:", response.status_code)
            print(response.text)
            return

        command = response.json().get("command")
        if not command:
            return

        print("명령 수신:", time.ticks_ms(), command)
        actuator = command.get("actuator")
        value = command.get("value")

        if actuator == "ventilation_fan":
            set_fan_level(value)
        elif actuator == "water_sprayer":
            print("물 뿌리기:", "ON" if value else "OFF")
    except Exception as error:
        print("명령 조회 오류:", repr(error))
    finally:
        close_response(response)


print("COWOW ESP32 시작")
print("장치 ID:", DEVICE_ID)
print("펌웨어:", FIRMWARE_VERSION)
print("명령 조회 주기:", COMMAND_INTERVAL_MS, "ms")

release_motor()
_thread.start_new_thread(motor_worker, ())
connect_wifi()
time.sleep(2)

measure_air_quality()
if measure_dht11():
    send_telemetry()
if wlan.isconnected():
    send_heartbeat()

try:
    while True:
        connect_wifi()
        now = time.ticks_ms()

        if (
            wlan.isconnected()
            and time.ticks_diff(now, last_command_at)
            >= COMMAND_INTERVAL_MS
        ):
            last_command_at = now
            poll_command()

        if (
            wlan.isconnected()
            and time.ticks_diff(now, last_heartbeat_at)
            >= HEARTBEAT_INTERVAL_MS
        ):
            last_heartbeat_at = now
            send_heartbeat()

        if (
            time.ticks_diff(now, last_sensor_at)
            >= SENSOR_INTERVAL_MS
        ):
            last_sensor_at = now
            measure_air_quality()
            if measure_dht11():
                send_telemetry()

        time.sleep_ms(10)
except KeyboardInterrupt:
    print("프로그램 중지")
finally:
    fan_level = 0
    time.sleep_ms(50)
    release_motor()
    print("모터 코일 해제")
