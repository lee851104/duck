"""未啟用的 LINE Messaging API 接收轉接器；不註冊路由、不寫資料、不呼叫外部服務。

只接受原始 bytes，驗章後轉為事件。去重、持久化、排程與訂單轉換由未來接收端負責。
目前支援官方 user/group/room 來源，不代表支援 OpenChat。
"""
import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


TAIPEI = timezone(timedelta(hours=8))


class IntakeError(ValueError):
    """請求或事件格式不符；不在錯誤訊息中帶入原文或憑證。"""


class SignatureError(IntakeError):
    """Webhook 簽章缺漏或不符。"""


@dataclass(frozen=True)
class IncomingEvent:
    destination: str
    event_id: str
    event_type: str
    source_type: str
    chat_id: str
    sender_id: str | None
    occurred_at: datetime
    is_redelivery: bool
    kind: str  # text / image / unsend / unsupported
    message_id: str | None
    text: str | None

    @property
    def dedupe_key(self):
        """供未來資料庫 UNIQUE 約束使用；此模組本身不記錄已收到的事件。"""
        return (self.destination, self.event_id)

    @property
    def conversation_key(self):
        return (self.destination, self.source_type, self.chat_id)

    def to_chat_message(self, display_name):
        """明確提供顯示名稱後，轉成既有 AI 文字格式；不觸發分類或轉單。

        LINE 事件沒有暱稱。呼叫端需先解決身分及名稱缺漏，不以暱稱認定店員。
        """
        if self.kind != 'text':
            raise IntakeError('只有文字事件能轉成聊天文字')
        if (not isinstance(display_name, str) or not display_name.strip()
                or any(ord(c) < 32 or c in '\x7f\u0085\u2028\u2029' for c in display_name)):
            raise IntakeError('顯示名稱必須是非空白單行文字')
        from .line_chat import Message
        local = self.occurred_at.astimezone(TAIPEI)
        at = local.strftime('%H:%M')
        return Message(local.date().isoformat(), at, f'{at} {display_name.strip()} {self.text}')


def _object(value, field):
    if not isinstance(value, dict):
        raise IntakeError(f'{field} 必須是物件')
    return value


def _string(obj, field):
    value = obj.get(field)
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f'{field} 必須是非空白字串')
    return value


def _event(destination, value):
    event = _object(value, 'event')
    event_id = _string(event, 'webhookEventId')
    event_type = _string(event, 'type')
    source = _object(event.get('source'), 'source')
    source_type = _string(source, 'type')
    id_field = {'user': 'userId', 'group': 'groupId', 'room': 'roomId'}.get(source_type)
    if id_field is None:
        raise IntakeError('尚未支援此聊天室來源')
    chat_id = _string(source, id_field)
    sender_id = _string(source, 'userId') if 'userId' in source else None
    timestamp = event.get('timestamp')
    if type(timestamp) is not int or timestamp < 0:
        raise IntakeError('timestamp 必須是非負整數毫秒')
    try:
        occurred_at = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(milliseconds=timestamp)
    except OverflowError:
        raise IntakeError('timestamp 超出支援範圍') from None
    delivery = _object(event.get('deliveryContext'), 'deliveryContext')
    redelivery = delivery.get('isRedelivery')
    if type(redelivery) is not bool:
        raise IntakeError('isRedelivery 必須是布林值')
    kind, message_id, text = 'unsupported', None, None
    if event_type == 'message':
        message = _object(event.get('message'), 'message')
        message_id = _string(message, 'id')
        message_type = _string(message, 'type')
        if message_type == 'text':
            text = message.get('text')
            if not isinstance(text, str):
                raise IntakeError('text 必須是字串')
            kind = 'text'
        elif message_type == 'image':
            kind = 'image'
    elif event_type == 'unsend':
        message_id = _string(_object(event.get('unsend'), 'unsend'), 'messageId')
        kind = 'unsend'
    return IncomingEvent(destination, event_id, event_type, source_type, chat_id,
                         sender_id, occurred_at, redelivery, kind, message_id, text)


def decode_webhook(body, signature, *, channel_secret, expected_destination):
    """驗證原始請求並回傳 tuple[IncomingEvent, ...]；整批有效才回傳。

    body 必須直接取自 HTTP 原始內容，不可先 JSON 解析再序列化。
    events=[] 為合法驗證請求。重送不會被略過，需在持久化時原子去重。
    """
    if not isinstance(body, bytes):
        raise IntakeError('body 必須是原始 bytes')
    if not isinstance(channel_secret, str) or not channel_secret.strip():
        raise IntakeError('尚未設定 channel secret')
    if not isinstance(expected_destination, str) or not expected_destination.strip():
        raise IntakeError('尚未設定接收帳號 ID')
    if not isinstance(signature, str) or not signature.isascii() or not signature:
        raise SignatureError('Webhook 簽章缺漏或不符')
    expected = base64.b64encode(hmac.new(channel_secret.encode('utf-8'), body,
                                       hashlib.sha256).digest()).decode('ascii')
    if not hmac.compare_digest(expected, signature):
        raise SignatureError('Webhook 簽章缺漏或不符')
    try:
        payload = _object(json.loads(body.decode('utf-8')), 'payload')
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IntakeError('Webhook 必須是 UTF-8 JSON') from None
    destination = _string(payload, 'destination')
    if destination != expected_destination:
        raise IntakeError('Webhook 接收帳號不符')
    events = payload.get('events')
    if not isinstance(events, list):
        raise IntakeError('events 必須是陣列')
    return tuple(_event(destination, event) for event in events)
