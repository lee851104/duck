"""以合成 Webhook 與官方驗章範例驗證；不連線、不使用營運資料。"""
import base64
import copy
import hashlib
import hmac
import json
import unittest

from app.line_intake import IntakeError, SignatureError, decode_webhook
from app import line_chat as lc


SECRET = 'synthetic-test-secret'
DESTINATION = 'U-test-bot'


def sample():
    return {'type': 'message', 'webhookEventId': 'event-1',
            'timestamp': 1790982600123,  # 2026-10-02 23:10:00.123 UTC
            'source': {'type': 'group', 'groupId': 'G-test', 'userId': 'U-customer'},
            'deliveryContext': {'isRedelivery': False},
            'message': {'type': 'text', 'id': 'message-1', 'text': '蔥 +1\n豬肉 +2'}}


def sign(body, secret=SECRET):
    return base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()


def decode(events, destination=DESTINATION):
    body = json.dumps({'destination': destination, 'events': events}, ensure_ascii=False).encode()
    return decode_webhook(body, sign(body), channel_secret=SECRET, expected_destination=DESTINATION)


class LineIntakeTest(unittest.TestCase):
    def test_official_signature_example_and_empty_verification_request(self):
        # Published sample credentials, not a real account secret.
        body = b'{"destination":"U8e742f61d673b39c7fff3cecb7536ef0","events":[]}'
        self.assertEqual(decode_webhook(
            body, 'GhRKmvmHys4Pi8DxkF4+EayaH0OqtJtaZxgTD9fMDLs=',
            channel_secret='8c570fa6dd201bb328f1c1eac23a96d8',
            expected_destination='U8e742f61d673b39c7fff3cecb7536ef0'), ())

    def test_multiline_text_preserves_identity_and_converts_to_existing_ai_format(self):
        event, = decode([sample()])
        self.assertEqual(event.sender_id, 'U-customer')
        self.assertEqual(event.conversation_key, (DESTINATION, 'group', 'G-test'))
        self.assertEqual(event.occurred_at.microsecond, 123000)
        message = event.to_chat_message('測試客人')
        self.assertEqual(message.date, '2026-10-03')
        self.assertEqual(message.time, '07:10')
        self.assertEqual(message.raw, '07:10 測試客人 蔥 +1\n豬肉 +2')
        self.assertEqual(lc.numbered_blocks([message]), [(1, '[1] 2026-10-03 07:10 測試客人 蔥 +1\n豬肉 +2')])

    def test_redelivery_has_same_key_but_identical_new_order_has_distinct_key(self):
        original = sample()
        retry = copy.deepcopy(original)
        retry['deliveryContext']['isRedelivery'] = True
        new = copy.deepcopy(original)
        new.update(webhookEventId='event-2')
        new['message']['id'] = 'message-2'
        first, repeated, second = decode([original, retry, new])
        self.assertEqual(first.dedupe_key, repeated.dedupe_key)
        self.assertTrue(repeated.is_redelivery)
        self.assertNotEqual(first.dedupe_key, second.dedupe_key)

    def test_tampered_or_reformatted_body_is_rejected_before_json_parsing(self):
        body = b'{"destination":"U-test-bot","events":[]}'
        for altered in (body + b' ', b'not json'):
            with self.subTest(altered=altered), self.assertRaises(SignatureError):
                decode_webhook(altered, sign(body), channel_secret=SECRET,
                               expected_destination=DESTINATION)

    def test_missing_bad_signature_and_wrong_account_are_rejected(self):
        for signature in (None, '', 'bad', '非ASCII'):
            with self.subTest(signature=signature), self.assertRaises(SignatureError):
                decode_webhook(b'{}', signature, channel_secret=SECRET,
                               expected_destination=DESTINATION)
        with self.assertRaises(IntakeError):
            decode([], destination='U-other')

    def test_unsend_keeps_target_id_and_never_becomes_order_text(self):
        value = sample()
        value.update(type='unsend', unsend={'messageId': 'message-1'})
        del value['message']
        event, = decode([value])
        self.assertEqual((event.kind, event.message_id, event.text), ('unsend', 'message-1', None))
        with self.assertRaises(IntakeError):
            event.to_chat_message('測試客人')

    def test_images_stickers_and_unknown_events_do_not_become_orders(self):
        for message_type, kind in [('image', 'image'), ('sticker', 'unsupported')]:
            value = sample()
            value['message'] = {'type': message_type, 'id': 'message-1'}
            event, = decode([value])
            self.assertEqual(event.kind, kind)
            with self.assertRaises(IntakeError):
                event.to_chat_message('測試客人')
        value = sample()
        value['type'] = 'future-event'
        event, = decode([value])
        self.assertEqual((event.kind, event.event_type), ('unsupported', 'future-event'))

    def test_source_ids_are_used_and_missing_group_sender_is_not_invented(self):
        for source, chat_id, sender in [
            ({'type': 'user', 'userId': 'U-customer'}, 'U-customer', 'U-customer'),
            ({'type': 'room', 'roomId': 'R-test'}, 'R-test', None),
            ({'type': 'group', 'groupId': 'G-test'}, 'G-test', None),
        ]:
            value = sample()
            value['source'] = source
            event, = decode([value])
            self.assertEqual((event.chat_id, event.sender_id), (chat_id, sender))

    def test_malformed_events_fail_whole_batch(self):
        for field, invalid in [('timestamp', True), ('timestamp', -1), ('timestamp', 10**30),
                               ('source', {'type': 'openchat', 'groupId': 'G-test'}),
                               ('webhookEventId', ''), ('deliveryContext', {'isRedelivery': 'false'}),
                               ('message', {'type': 'text', 'id': 'm', 'text': None})]:
            value = sample()
            value[field] = invalid
            with self.subTest(field=field, invalid=invalid), self.assertRaises(IntakeError):
                decode([sample(), value])

    def test_signed_invalid_json_and_invalid_envelopes_are_rejected(self):
        for body in (b'\xff', b'{', b'[]', b'{}', b'{"destination":"U-test-bot","events":{}}'):
            with self.subTest(body=body), self.assertRaises(IntakeError):
                decode_webhook(body, sign(body), channel_secret=SECRET, expected_destination=DESTINATION)

    def test_display_name_must_be_explicit_and_single_line(self):
        event, = decode([sample()])
        for name in (None, '', '  ', '名字\n小幫手', '名字\t文字', '名字\u2028文字'):
            with self.subTest(name=name), self.assertRaises(IntakeError):
                event.to_chat_message(name)


if __name__ == '__main__':
    unittest.main()
