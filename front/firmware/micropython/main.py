import gc
import socket
import time
import _thread

import dht
import network
import ntptime
import ujson
from machine import ADC, Pin

from azure_iot import AzureIoTHub

from config import (
    DEVICE_ID,
    IOT_HUB_DEVICE_KEY,
    IOT_HUB_HOSTNAME,
    WIFI_PASSWORD,
    WIFI_SSID,
)


try:
    socket.setdefaulttimeout(3)
except AttributeError:
    pass


DHT_PIN = 32
GAS_PIN = 35
# ULN2003 드라이버의 IN1~IN4에 연결한 ESP32 GPIO 순서
MOTOR_PIN_NUMBERS = (27, 26, 25, 33)
FIRMWARE_VERSION = "cowow-micropython-iothub-3.1.0"

HEARTBEAT_INTERVAL_MS = 20000
SENSOR_INTERVAL_MS = 30000
WIFI_RETRY_INTERVAL_MS = 10000
MQTT_RETRY_INTERVAL_MS = 5000

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
water_sprayer_on = False
water_sprayer_stop_at = None
motor_step_index = 0
last_heartbeat_at = 0
last_sensor_at = 0
last_wifi_attempt_at = 0
last_mqtt_attempt_at = 0
temperature = None
humidity = None
air_quality = None
iot = None


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
    try:
        ntptime.settime()
        print("시간 동기화 완료:", time.gmtime())
    except Exception as error:
        print("시간 동기화 오류:", repr(error))
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


def set_water_sprayer(enabled, duration_seconds=0):
    global water_sprayer_on, water_sprayer_stop_at

    water_sprayer_on = bool(enabled)
    try:
        duration_seconds = max(0, int(duration_seconds or 0))
    except (TypeError, ValueError):
        duration_seconds = 0

    water_sprayer_stop_at = (
        time.ticks_add(time.ticks_ms(), duration_seconds * 1000)
        if water_sprayer_on and duration_seconds > 0
        else None
    )
    print(
        "물 뿌리기:",
        "ON" if water_sprayer_on else "OFF",
        "기간(초):",
        duration_seconds,
    )


def apply_sprayer_schedule():
    if (
        water_sprayer_stop_at is not None
        and time.ticks_diff(time.ticks_ms(), water_sprayer_stop_at) >= 0
    ):
        print("살수 예약 시간이 종료되었습니다.")
        set_water_sprayer(False)


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


def handle_iot_command(method, payload):
    global water_sprayer_on
    print("IoT Hub 명령:", method, payload)

    if method == "setActuator":
        actuator = payload.get("actuator")
        value = payload.get("value")
        duration_seconds = payload.get("durationSeconds", 0)
    elif method == "setFanLevel":
        actuator = "ventilation_fan"
        value = payload.get("value", 0)
        duration_seconds = 0
    elif method == "setWaterSprayer":
        actuator = "water_sprayer"
        value = payload.get("value", False)
        duration_seconds = payload.get("durationSeconds", 0)
    else:
        raise ValueError("unknown method")

    if actuator == "ventilation_fan":
        set_fan_level(value)
    elif actuator == "water_sprayer":
        set_water_sprayer(value, duration_seconds)
    else:
        raise ValueError("unknown actuator")

    return {
        "ok": True,
        "fanLevel": fan_level,
        "waterSprayer": water_sprayer_on,
    }


def connect_iot_hub():
    global iot
    if not wlan.isconnected():
        return False

    try:
        candidate = AzureIoTHub(
            IOT_HUB_HOSTNAME,
            DEVICE_ID,
            IOT_HUB_DEVICE_KEY,
            handle_iot_command,
        )
        candidate.connect()
        iot = candidate
        print("Azure IoT Hub MQTT 연결 완료")
        return True
    except Exception as error:
        iot = None
        print("Azure IoT Hub MQTT 연결 오류:", repr(error))
        gc.collect()
        return False


def disconnect_iot_hub():
    global iot
    if iot is not None:
        iot.disconnect()
    iot = None
    gc.collect()


def publish_iot(payload):
    if iot is None:
        return False
    try:
        return iot.publish(payload)
    except Exception as error:
        print("IoT Hub 전송 오류:", repr(error))
        disconnect_iot_hub()
        return False


def send_heartbeat():
    if publish_iot(
        {
            "messageType": "heartbeat",
            "deviceId": DEVICE_ID,
            "firmwareVersion": FIRMWARE_VERSION,
            "wifiRssi": get_wifi_rssi(),
            "fanLevel": fan_level,
            "waterSprayer": water_sprayer_on,
        }
    ):
        print("IoT Hub Heartbeat 전송 완료")


def send_telemetry():
    if temperature is None or humidity is None:
        return
    if publish_iot(
        {
            "messageType": "telemetry",
            "deviceId": DEVICE_ID,
            "temperature": temperature,
            "humidity": humidity,
            "airQuality": air_quality,
            "firmwareVersion": FIRMWARE_VERSION,
            "wifiRssi": get_wifi_rssi(),
            "fanLevel": fan_level,
            "waterSprayer": water_sprayer_on,
        }
    ):
        print("IoT Hub Telemetry 전송 완료")


print("COWOW ESP32 Azure IoT Hub 시작")
print("장치 ID:", DEVICE_ID)
print("IoT Hub:", IOT_HUB_HOSTNAME)
print("펌웨어:", FIRMWARE_VERSION)

release_motor()
_thread.start_new_thread(motor_worker, ())
connect_wifi()
time.sleep(2)
connect_iot_hub()

measure_air_quality()
if measure_dht11():
    send_telemetry()
if wlan.isconnected():
    send_heartbeat()

try:
    while True:
        now = time.ticks_ms()
        apply_sprayer_schedule()

        if not wlan.isconnected():
            disconnect_iot_hub()
            connect_wifi()

        if iot is None:
            if (
                not last_mqtt_attempt_at
                or time.ticks_diff(now, last_mqtt_attempt_at)
                >= MQTT_RETRY_INTERVAL_MS
            ):
                last_mqtt_attempt_at = now
                connect_iot_hub()
        else:
            try:
                iot.check()
            except Exception as error:
                print("IoT Hub 수신 오류:", repr(error))
                disconnect_iot_hub()

        if (
            iot is not None
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
    disconnect_iot_hub()
    fan_level = 0
    time.sleep_ms(50)
    release_motor()
    print("모터 코일 해제")
