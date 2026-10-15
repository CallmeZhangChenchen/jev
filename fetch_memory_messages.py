#!/usr/bin/env python3
# 读取 clue_event_history_clue_ids_0704.txt 中的 (clue_id, agent_id)，
# 逐个调用 get_memory_message_list 拉取历史对话，
# 只保留 "系统通知:绑定评估报告成功" 之后的消息，
# 按 all_memory_messages_filtered_v4.json 的格式写入新文件。

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_FILE = os.path.join(BASE_DIR, 'clue_event_history_clue_ids_0704.txt')
OUTPUT_FILE = os.path.join(BASE_DIR, 'all_memory_messages_filtered_v5.json')
API_URL = 'https://agentic.yxqiche.com/yiche/fapi/get_memory_message_list'
APP_ID = 'vehicle_loan_submission'
MARKER_CONTENT = '系统通知:绑定评估报告成功'


def fetch_session(clue_id, agent_id, retries=2):
    payload = json.dumps({
        'session_ids': [clue_id],
        'agent_id': agent_id,
        'app_id': APP_ID,
    }).encode('utf-8')
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                API_URL, data=payload,
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode('utf-8'))
            if body.get('code') != 0:
                raise RuntimeError(f"code={body.get('code')}, msg={body.get('message')}")
            data = body.get('data') or {}
            # 单 session 时 data 是对象；若返回列表则取对应项
            if isinstance(data, list):
                for item in data:
                    if item.get('session_id') == clue_id:
                        return item
                return {}
            return data
        except Exception as e:
            if attempt >= retries:
                raise
            time.sleep(1)
    return {}


def filter_after_marker(messages):
    """保留 marker 消息及之后（含 marker）的消息；找不到 marker 返回 None"""
    for i, msg in enumerate(messages):
        if msg.get('role') == 'user' and (msg.get('content') or '').strip() == MARKER_CONTENT:
            return messages[i:]
    return None


def main():
    pairs = []
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split(',')
            clue_id = parts[0].strip()
            agent_id = parts[1].strip() if len(parts) > 1 else ''
            pairs.append((clue_id, agent_id))

    print(f'共 {len(pairs)} 个 (clue_id, agent_id)')

    result_data = []
    ok = fail = no_marker = 0
    for idx, (clue_id, agent_id) in enumerate(pairs, 1):
        try:
            session = fetch_session(clue_id, agent_id)
            messages = session.get('chat_messages') or []
            profile_data = session.get('profile_data') or {}
            filtered = filter_after_marker(messages)
            if filtered is None:
                no_marker += 1
                print(f'[{idx}/{len(pairs)}] {clue_id} ({agent_id}): '
                      f'共 {len(messages)} 条，未找到绑定评估报告标记，保留为空')
                filtered = []
            else:
                print(f'[{idx}/{len(pairs)}] {clue_id} ({agent_id}): '
                      f'共 {len(messages)} 条，自标记起保留 {len(filtered)} 条')
            result_data.append({
                'session_id': clue_id,
                'chat_messages': filtered,
                'profile_data': profile_data,
            })
            ok += 1
        except Exception as e:
            fail += 1
            print(f'[{idx}/{len(pairs)}] {clue_id} ({agent_id}): 请求失败 - {e}',
                  file=sys.stderr)
        time.sleep(0.1)

    output = {'code': 0, 'message': 'OK', 'data': result_data}
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=4)

    print(f'\n完成：成功 {ok}，失败 {fail}，无标记 {no_marker}')
    print(f'已写入 {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
