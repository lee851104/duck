"""LINE「儲存聊天」匯出檔解析與 OpenAI 訂單轉換；不依賴 Flask，方便單獨測試。

匯出格式：日期列「2026.10.02 星期五」，留言列「10:54 暱稱 內文」，其餘行接續上一則。
暱稱與內文只以空白分隔，暱稱也可能含空白，所以不在這裡切開，交給 AI 判斷。
"""
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import date, time as clock

STAFF_NAMES = ('菜騎鴨官方小幫手', '鴨老闆', '小幫手', 'Auto-reply')
TAIL_SIZE = 300  # 記住最後幾則留言的指紋，用來找上次匯入到哪裡
ANCHOR_RUN = 5  # 至少連續幾則吻合才算找到位置
MAX_MISSING_TAIL = 30  # 上次最後幾則最多容許被收回幾則
WEEKDAYS = '一二三四五六日'
DATE_RE = re.compile(r'^(\d{4})[./](\d{2})[./](\d{2})'
                     r'(?:\s*星期[一二三四五六日天]|\s*[（(][一二三四五六日][）)])\s*$')
MSG_RE = re.compile(r'^(?:(上午|下午)(\d{1,2})|(\d{2})):([0-5]\d)[ \t](.*)$')
IMAGE_WORDS = ('圖片', '相片', '照片', '影片')
SKIP_WORDS = ('貼圖', '語音訊息', '檔案', '已分享記事本。')
SYSTEM_ENDINGS = ('加入聊天', '離開聊天', '退出社群')


@dataclass
class Message:
    date: str  # 2026-10-02
    time: str  # 10:54
    raw: str  # 第一行含時間，後面接續原文其他行

    @property
    def lines(self):
        return self.raw.split('\n')

    @property
    def body(self):
        """第一行去掉時間後的暱稱與內文。"""
        m = MSG_RE.match(self.lines[0])
        return m.group(5) if m else self.lines[0]

    @property
    def multiline(self):
        return '\n' in self.raw

    @property
    def key(self):
        return (self.date, self.time)

    @property
    def fp(self):
        return hashlib.sha256(f'{self.date}\n{self.raw}'.encode('utf-8')).hexdigest()[:24]

    def text(self):
        return f'{self.date} {self.time} ' + '\n'.join([self.body] + self.lines[1:])


def decode_export(data):
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        return data.decode('utf-16')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError('檔案不是 UTF-8 文字，請上傳 LINE「儲存聊天」匯出的 .txt') from None


def chat_name(filename):
    stem = re.sub(r'\.txt$', '', str(filename or ''), flags=re.I)
    stem = re.sub(r'^\[LINE\]\s*', '', stem)
    return re.sub(r'\s*\(\d+\)$', '', stem).strip()[:120] or 'LINE 聊天'  # Windows 重複存檔會加 (1)


def parse_date_line(line):
    m = DATE_RE.match(line.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def parse_time(line):
    m = MSG_RE.match(line)
    if not m:
        return None
    ampm, h12, h24, minute = m.group(1), m.group(2), m.group(3), m.group(4)
    if ampm:
        hour = int(h12)
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == '下午' else 0)
    else:
        hour = int(h24)
        if hour > 23:
            return None
    return f'{hour:02d}:{minute}'


def parse_chat(text):
    messages, day, current = [], None, None
    for line in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        found = parse_date_line(line)
        if found:
            day, current = found, None
            continue
        if day is None:
            continue  # 檔頭：[LINE] 聊天記錄、儲存日期等
        at = parse_time(line)
        if at:
            current = Message(day, at, line)
            messages.append(current)
        elif current is not None:
            current.raw += '\n' + line
    for m in messages:
        m.raw = m.raw.rstrip()
    return messages


def parse_since(text):
    """'2026-10-03'、'2026-10-03 09:00' 或 datetime-local 的 '2026-10-03T09:00'。"""
    m = re.fullmatch(r'\s*(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?\s*', str(text or ''))
    if not m:
        raise ValueError('開始時間格式應為 YYYY-MM-DD HH:MM')
    try:
        day = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        at = clock(int(m.group(4) or 0), int(m.group(5) or 0))
    except ValueError:
        raise ValueError('開始時間不存在') from None
    return (day.isoformat(), f'{at:%H:%M}')


def find_new_messages(tail, messages):
    """在新匯出檔中找到上次最後幾則留言，回傳 (新留言, 不見了的舊留言數)；找不到回傳 None。

    上次最後幾則若被收回，會往前找仍存在的留言當位置。同一分鐘同內容的留言只要在
    上次位置之後，仍然算新的。
    """
    if not tail:
        return list(messages), 0
    fps = [m.fp for m in messages]
    where = {}
    for i, f in enumerate(fps):
        where.setdefault(f, []).append(i)
    for skipped in range(min(len(tail), MAX_MISSING_TAIL + 1)):
        end = len(tail) - skipped
        run = min(ANCHOR_RUN, end)
        seq = tail[end - run:end]
        for last in reversed(where.get(seq[-1], [])):
            start = last - run + 1
            if start >= 0 and fps[start:last + 1] == seq:
                after = set(tail[end:])  # 位置之後但仍存在的舊留言不算新的
                new = [m for m in messages[last + 1:] if m.fp not in after]
                return new, sum(1 for f in tail[end:] if f not in where)
    return None


def is_staff(message, staff=STAFF_NAMES):
    return any(message.body.startswith(name) for name in staff if name)


def classify(message, staff=STAFF_NAMES):
    """customer＝客人文字留言（送 AI 判斷）；其餘不送 AI。"""
    body = message.body.rstrip()
    if is_staff(message, staff):
        return 'staff'
    if not message.multiline:
        if body.endswith('已收回訊息'):
            return 'recall'
        if any(body.endswith(' ' + w) for w in IMAGE_WORDS):
            return 'image'
        if any(body.endswith(' ' + w) for w in SKIP_WORDS) or body.endswith(SYSTEM_ENDINGS):
            return 'other'
    return 'customer'


def squeeze_emoji(text):
    return re.sub(r'(?:\(emoji\))+', '□', text)


def latest_menu(messages, staff=STAFF_NAMES):
    for m in reversed(messages):
        if m.multiline and '今日菜單' in m.lines[0] and is_staff(m, staff):
            lines = [squeeze_emoji(x).strip() for x in m.lines]
            return {'date': m.date, 'time': m.time,
                    'text': '\n'.join(x for x in lines if x.strip('□ '))[:8000]}
    return None


# ---------------------------------------------------------------- OpenAI

SYSTEM_PROMPT = """你是台中「菜騎鴨」生鮮蔬果行的訂單整理助理。
使用者訊息有今日菜單與 LINE 社群的新留言。每則留言以「[編號] 日期 時間 暱稱 內文」開頭；暱稱與內文以空白分隔，暱稱本身可能含空白或社區戶號，請自行判斷。□ 代表無法顯示的表情符號。

請只把「客人喊單」整理成訂單：
1. 問價、問有沒有貨、閒聊、道謝、回覆店家、要照片等都不是訂單，不要輸出。
2. 一則喊單輸出一筆訂單。客人補充或更改先前的訂單（例如「再加一包蔥」「蔥改兩把」「取消」）時，action 分別填「追加」「修改」「取消」，把變更內容寫進 items 或 note。
3. 同一筆訂單若分成好幾則留言（例如先寫商品、下一則補地點），source_ids 列出全部編號。
4. location：外送地點、社區名稱、棟別戶號，或「自取」。常見寫法如「聯悅聚B6-3」「協和丰景 6D3」「A15-1」，寫在暱稱裡的也算。沒寫就留空。
5. items 每項商品一列：
   - product_id：若這項明確就是【店內商品清單】的某個商品（名稱可略有不同，例如「豬五花」對「台灣豬五花(火)」），填該商品的編號數字；清單上沒有的（例如生鮮蔬果）填 null，不要套用相似但不同的商品；
   - name：有對應商品時用店內商品名稱，否則用今日菜單上的名稱，都沒有就照客人寫法；
   - quantity 只填數字（「+1」「*2」「x4」「兩包」都轉成數字，「半斤」「半顆」填 0.5），看不出數量填 null；
   - unit 填單位（包、把、顆、斤、盒…），不確定可留空；
   - unit_price 只有留言、今日菜單或店內商品清單寫得出單價才填，否則 null，不要計算總價；寫的是整組的價格（例如「100/5入」，而 unit 是入或顆）時填 null，不要把整組價格當成每個的單價；
   - processing 填處理方式（切、剁、去皮、剖半、切丁、退冰…）；客人說「不要去皮」「不切」也要照寫；
   - note 填其他要求（要大顆、綠一點、多少元的量…）。
6. carrier：電子發票載具（以斜線開頭的手機條碼，例如 /IB8-+1S），沒有就空字串。
7. payment：付款或儲值相關說明（已匯款、末五碼、扣儲值金、貨到付款…），沒有就空字串。
8. note：整張訂單的其他說明（要冰＋姓氏、放管理室、晚送、自取時間…）。
9. 看不懂、不確定是不是訂單、找不到外送地點、或可能在改舊訂單時，needs_review 設 true，review_reason 簡短寫原因。不要猜測或捏造；沒有的文字欄位填空字串。
10. 全部使用繁體中文。"""

ORDER_SCHEMA = {
    'type': 'object', 'additionalProperties': False, 'required': ['orders'],
    'properties': {'orders': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'required': ['source_ids', 'customer', 'location', 'action', 'items', 'carrier', 'payment',
                     'note', 'needs_review', 'review_reason'],
        'properties': {
            'source_ids': {'type': 'array', 'items': {'type': 'integer'}},
            'customer': {'type': 'string'},
            'location': {'type': 'string'},
            'action': {'type': 'string', 'enum': ['新訂單', '追加', '修改', '取消']},
            'items': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'required': ['product_id', 'name', 'quantity', 'unit', 'unit_price', 'processing', 'note'],
                'properties': {
                    'product_id': {'type': ['integer', 'null']},
                    'name': {'type': 'string'},
                    'quantity': {'type': ['number', 'null']},
                    'unit': {'type': 'string'},
                    'unit_price': {'type': ['number', 'null']},
                    'processing': {'type': 'string'},
                    'note': {'type': 'string'}}}},
            'carrier': {'type': 'string'},
            'payment': {'type': 'string'},
            'note': {'type': 'string'},
            'needs_review': {'type': 'boolean'},
            'review_reason': {'type': 'string'}}}}}}

# 每 100 萬 tokens 的美元價格：(輸入, 快取輸入, 輸出)，2026-10-03 取自 OpenAI 價目頁
PRICES = {'gpt-6-luna': (0.10, 0.01, 0.50), 'gpt-6.1-sol': (2.00, 0.10, 10.00),
          'gpt-6-astra': (10.00, 1.00, 50.00), 'gpt-5-nano': (0.05, 0.005, 0.40),
          'gpt-4o-mini': (0.15, 0.075, 0.60)}


class AIError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def numbered_blocks(candidates):
    return [(i, f'[{i}] ' + squeeze_emoji(m.text())) for i, m in enumerate(candidates, 1)]


def chunk_blocks(blocks, max_chars=12000):
    chunks, current, size = [], [], 0
    for block in blocks:
        if current and size + len(block[1]) > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(block)
        size += len(block[1]) + 1
    if current:
        chunks.append(current)
    return chunks


def products_text(products):
    return '\n'.join(f"#{p['id']} {p['name']}｜{p['unit']}｜" + (f"${p['price']}" if p['price'] else '未定價')
                     for p in products)


def build_payload(model, products, menu_text, blocks, effort=None):
    # 固定內容放前面，讓 OpenAI 自動快取這段（價格約一折）。
    system = SYSTEM_PROMPT + '\n\n【店內商品清單】（#編號 名稱｜單位｜售價）\n' + (products or '（目前沒有商品）')
    user = ('【今日菜單（參考生鮮名稱與單價）】\n' + (menu_text or '（沒有菜單資料）')
            + '\n\n【新留言】\n' + '\n'.join(text for _, text in blocks))
    payload = {
        'model': model,
        'input': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}],
        'text': {'format': {'type': 'json_schema', 'name': 'line_orders', 'strict': True,
                            'schema': ORDER_SCHEMA}},
        'store': False,  # 客人資料不保存在 OpenAI 的回應紀錄
    }
    if effort:
        payload['reasoning'] = {'effort': effort}
    return payload


def ai_error(status, error, model):
    code = error.get('code') or error.get('type') or ''
    message = error.get('message') or ''
    if status == 401:
        return AIError('OpenAI 金鑰無效或已停用，請重新設定金鑰')
    if code == 'insufficient_quota':
        return AIError('OpenAI 額度（credits）不足，請到 OpenAI 帳戶加值')
    if code == 'model_not_found' or status == 404:
        return AIError(f'這個 OpenAI 帳號不能使用模型「{model}」')
    if status == 429 or status >= 500:
        return AIError(f'OpenAI 暫時忙碌（{status}），請稍後重試', retryable=True)
    return AIError(f'OpenAI 拒絕這次請求（{status} {code}）：{message}'[:300])


def http_send(api_key, url='https://api.openai.com/v1/responses', timeout=150):
    import requests

    def send(payload):
        try:
            response = requests.post(url, json=payload, timeout=timeout,
                                     headers={'Authorization': f'Bearer {api_key}'})
        except requests.RequestException:
            raise AIError('連不上 OpenAI，請檢查網路後重試', retryable=True) from None
        if response.status_code != 200:
            try:
                error = response.json().get('error') or {}
            except ValueError:
                error = {}
            raise ai_error(response.status_code, error, payload['model'])
        try:
            return response.json()
        except ValueError:
            raise AIError('OpenAI 回覆格式錯誤，請重試', retryable=True) from None
    return send


def send_with_retry(send, payload, delays=(3, 10)):
    for attempt in range(len(delays) + 1):
        try:
            return send(payload)
        except AIError as e:
            if not e.retryable or attempt == len(delays):
                raise
            time.sleep(delays[attempt])


def read_response(response):
    if response.get('status') == 'incomplete':
        reason = (response.get('incomplete_details') or {}).get('reason', '')
        raise AIError(f'OpenAI 回覆不完整（{reason}），請重試')
    texts = []
    for item in response.get('output') or []:
        if item.get('type') != 'message':
            continue
        for content in item.get('content') or []:
            if content.get('type') == 'output_text':
                texts.append(content.get('text', ''))
            elif content.get('type') == 'refusal':
                raise AIError('OpenAI 拒絕處理這批留言：' + content.get('refusal', '')[:200])
    if not texts and response.get('output_text'):
        texts = [response['output_text']]
    try:
        data = json.loads(''.join(texts))
    except ValueError:
        raise AIError('OpenAI 回覆的不是訂單資料，請重試') from None
    if not isinstance(data, dict) or not isinstance(data.get('orders'), list):
        raise AIError('OpenAI 回覆的不是訂單資料，請重試')
    return data, response.get('usage') or {}


def add_usage(total, usage):
    total['input_tokens'] = total.get('input_tokens', 0) + int(usage.get('input_tokens') or 0)
    total['output_tokens'] = total.get('output_tokens', 0) + int(usage.get('output_tokens') or 0)
    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens') or 0
    reasoning = (usage.get('output_tokens_details') or {}).get('reasoning_tokens') or 0
    total['cached_tokens'] = total.get('cached_tokens', 0) + int(cached)
    total['reasoning_tokens'] = total.get('reasoning_tokens', 0) + int(reasoning)
    return total


def estimate_cost(model, usage):
    """美元；未知模型回傳 None。"""
    prices = PRICES.get(model)
    if not prices:
        return None
    cached = usage.get('cached_tokens', 0)
    return ((usage.get('input_tokens', 0) - cached) * prices[0] + cached * prices[1]
            + usage.get('output_tokens', 0) * prices[2]) / 1_000_000
