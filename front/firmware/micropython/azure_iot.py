import time
import ubinascii
import uhashlib
import ujson

from umqtt.simple import MQTTClient


def _unix_time():
    value = time.time()
    if time.gmtime(0)[0] == 2000:
        value += 946684800
    return int(value)


def _url_encode(value):
    if isinstance(value, str):
        value = value.encode()
    safe = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~"
    result = ""
    for item in value:
        byte = item if isinstance(item, int) else ord(item)
        result += chr(byte) if byte in safe else "%%%02X" % byte
    return result


def _hmac_sha256(key, message):
    if len(key) > 64:
        key = uhashlib.sha256(key).digest()
    key += b"\x00" * (64 - len(key))
    outer = bytes(item ^ 0x5C for item in key)
    inner = bytes(item ^ 0x36 for item in key)
    digest = uhashlib.sha256(inner + message).digest()
    return uhashlib.sha256(outer + digest).digest()


class AzureIoTHub:
    def __init__(self, hostname, device_id, device_key, command_handler):
        self.hostname = hostname
        self.device_id = device_id
        self.device_key = device_key
        self.command_handler = command_handler
        self.client = None

    def _sas_token(self):
        resource = self.hostname.lower() + "/devices/" + self.device_id.lower()
        encoded_resource = _url_encode(resource)
        expiry = _unix_time() + 86400
        message = (encoded_resource + "\n" + str(expiry)).encode()
        key = ubinascii.a2b_base64(self.device_key)
        signature = ubinascii.b2a_base64(
            _hmac_sha256(key, message)
        ).strip()
        return (
            "SharedAccessSignature sr=" + encoded_resource
            + "&sig=" + _url_encode(signature)
            + "&se=" + str(expiry)
        )

    def connect(self):
        self.disconnect()
        username = (
            self.hostname + "/" + self.device_id
            + "/?api-version=2021-04-12"
        )
        client = MQTTClient(
            client_id=self.device_id.encode(),
            server=self.hostname,
            port=8883,
            user=username.encode(),
            password=self._sas_token().encode(),
            keepalive=60,
            ssl=True,
            ssl_params={"server_hostname": self.hostname},
        )
        client.set_callback(self._on_message)
        client.connect(clean_session=False)
        client.subscribe(b"$iothub/methods/POST/#")
        self.client = client

    def disconnect(self):
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None

    def check(self):
        if self.client is None:
            return
        self.client.check_msg()

    def publish(self, payload):
        if self.client is None:
            return False
        topic = ("devices/%s/messages/events/" % self.device_id).encode()
        self.client.publish(topic, ujson.dumps(payload))
        return True

    def _respond(self, request_id, status, payload):
        topic = (
            b"$iothub/methods/res/" + str(status).encode()
            + b"/?$rid=" + request_id
        )
        self.client.publish(topic, ujson.dumps(payload))

    def _on_message(self, topic, message):
        prefix = b"$iothub/methods/POST/"
        if not topic.startswith(prefix):
            return
        method = topic[len(prefix):].split(b"/", 1)[0].decode()
        marker = b"$rid="
        position = topic.find(marker)
        request_id = (
            topic[position + len(marker):].split(b"&", 1)[0]
            if position >= 0 else b"0"
        )
        try:
            payload = ujson.loads(message) if message else {}
            result = self.command_handler(method, payload)
            self._respond(request_id, 200, result or {"ok": True})
        except ValueError as error:
            self._respond(request_id, 400, {"error": str(error)})
        except Exception as error:
            self._respond(request_id, 500, {"error": repr(error)})
