#!/bin/bash
# 测试脚本 - Grafana 查询接口测试


echo "=== Grafana 查询接口测试 ==="
echo ""

# 配置
#HOST="http://127.0.0.1:8000"
# 测试（如需要）
#HOST="http://10.10.201.205/vesta/v2/engine_online/flow_schedule/custom_inference"
#TOKEN="YIXIN-347cbe99dd8669f52f849f1d851fced3"

# 线上
HOST="https://vesta2.yxqiche.com/vesta/v2/engine_online/flow_schedule/custom_inference"
TOKEN="YIXIN-19c9da966a4340c607602e51b07de669"


# 查询 clue_state
#echo "查询 clue_state:"
#curl -s -X POST "$HOST/api/grafana/query" \
#  -H "Authorization: Bearer $TOKEN" \
#  -H "Content-Type: application/json" \
#  -d '{
#    "requestId":"test_grafana_query_001",
#    "appId":"2067518537974419456",
#    "data":{
#      "sql":"SELECT clue_id, current_clue_stage, processor, record_valid FROM clue_state WHERE record_valid = %s LIMIT %s",
#      "params":["active", 3]
#    }
#  }' | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))"
#echo ""
#
#
# 查询 clue_event_history: customer_del_cancel_success / failed 每 clue 汇总
# 参数：
#   start_date - 起始日期（含）
#   end_date   - 结束日期（不含）
echo "查询 clue_event_history 汇总 (customer_del_cancel_success/failed):"

read -r -d '' SQL_3 <<'SQL'
SELECT
    clue_id
FROM clue_event_history
WHERE event_type IN (%s, %s)
  AND enter_time_ms >= UNIX_TIMESTAMP(%s) * 1000
  AND enter_time_ms <  UNIX_TIMESTAMP(%s) * 1000
GROUP BY clue_id
SQL
export SQL_3

read -r -d '' SQL_4 <<'SQL'
SELECT distinct clue_id
  FROM clue_state
  WHERE record_valid = 'active'
    AND current_clue_stage >= '2'
    AND JSON_SEARCH(ab_strategy, 'one', '10002_planb') IS NOT NULL
    # AND JSON_UNQUOTE(JSON_EXTRACT(stage_details, '$."2".is_pre_check_mode')) = '1'
  ORDER BY updated_at_ms DESC;
SQL
export SQL_4

read -r -d '' SQL_5 <<'SQL'
SELECT distinct s.clue_id
  FROM clue_state s
  JOIN wechat_clue_detail d ON d.clue_id = s.clue_id
  WHERE s.record_valid = 'active'
    AND s.current_clue_stage >= '2'
    AND JSON_SEARCH(s.ab_strategy, 'one', '10002_firstqr') IS NOT NULL
    AND JSON_UNQUOTE(JSON_EXTRACT(s.stage_details, '$."2".is_pre_check_mode')) = '1'
    AND d.pre_check_mode = '1'
  ORDER BY s.updated_at_ms DESC;
SQL
export SQL_5

read -r -d '' SQL_6 <<'SQL'
SELECT distinct s.clue_id, s.agent_id
  FROM clue_state s
  JOIN wechat_clue_detail d ON d.clue_id = s.clue_id
  WHERE s.record_valid = 'active'
    AND s.current_clue_stage = '3'
    AND s.created_at_ms >= UNIX_TIMESTAMP(%s) * 1000
    AND s.created_at_ms <  UNIX_TIMESTAMP(%s) * 1000
  ORDER BY s.updated_at_ms DESC;
SQL
export SQL_6




#PAYLOAD_3=$(python3 -c "
#import json, os
#print(json.dumps({
#    'requestId': 'test_grafana_query_003',
#    'appId': '2067518537974419456',
#    'data': {
#        'sql': os.environ['SQL_3'],
#        'params': [
#            'customer_del_cancel_success',
#            'customer_del_cancel_failed',
#            '2026-07-03 00:00:00',
#            '2026-07-29 00:00:00',
#        ]
#    }
#}, ensure_ascii=False))
#")

PAYLOAD_3=$(python3 -c "
import json, os
print(json.dumps({
    'requestId': 'test_grafana_query_003',
    'appId': '2067518537974419456',
    'data': {
        'sql': os.environ['SQL_6'],
        'params': [
          '2026-10-12 00:00:00',
          '2026-10-14 00:00:00',
      ]
    }
}, ensure_ascii=False))
")

OUT_FILE_3="$(dirname "$0")/clue_event_history_clue_ids_0704.txt"
curl -s -X POST "$HOST/api/grafana/mysql/query" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$PAYLOAD_3" | python3 -c "
import json, sys
resp = json.load(sys.stdin)
out_path = '$OUT_FILE_3'
results = (resp.get('data') or {}).get('results') or []
with open(out_path, 'w', encoding='utf-8') as f:
    for row in results:
        cid = row.get('clue_id')
        if cid:
            f.write(str(cid) + ',' + str(row.get('agent_id') or '') + '\n')
print(f'共 {len(results)} 条 clue_id，已写入 {out_path}')
print(f'code={resp.get(\"code\")}, msg={resp.get(\"msg\")}')
"
echo ""
#
#
## 查询 clue_state + clue_conversation_message：会话历史聚合
## 参数：
##   start_date - 起始日期（含）
##   end_date   - 结束日期（不含）
## 注意：GROUP_CONCAT 默认上限 1024 字节，可能被截断；服务端 SQL 白名单只允许 SELECT/WITH，
##      因此这里没有 SET SESSION group_concat_max_len，如需完整会话请在 DB 层调大该参数或换成拉明细
# 测试（如需要）
#HOST="http://10.10.201.205/vesta/v2/engine_online/flow_schedule/custom_inference"
#TOKEN="YIXIN-347cbe99dd8669f52f849f1d851fced3"
#
## 线上
#HOST="https://vesta2.yxqiche.com/vesta/v2/engine_online/flow_schedule/custom_inference"
#TOKEN="YIXIN-19c9da966a4340c607602e51b07de669"
#echo "查询 会话历史聚合 (clue_state + clue_conversation_message):"
#
#read -r -d '' SQL_4 <<'SQL'
#SELECT
#    m.clue_id,
#    FROM_UNIXTIME(s.created_at_ms / 1000)             AS clue_created_at,
#    COUNT(*)                                          AS msg_count,
#    MIN(FROM_UNIXTIME(m.timestamp_ms / 1000))         AS first_msg_time,
#    MAX(FROM_UNIXTIME(m.timestamp_ms / 1000))         AS last_msg_time,
#    GROUP_CONCAT(
#        JSON_OBJECT(
#            'msg_id',       m.msg_id,
#            'time',         FROM_UNIXTIME(m.timestamp_ms / 1000),
#            'role',         m.role,
#            'msg_type',     m.msg_type,
#            'content_type', m.content_type,
#            'delivered',    m.delivered,
#            'content',      m.content
#        )
#        ORDER BY m.timestamp_ms ASC
#        SEPARATOR '\n---\n'
#    )                                                 AS conversation_history
#FROM clue_state s
#JOIN clue_conversation_message m ON m.clue_id = s.clue_id
#WHERE s.created_at_ms >= UNIX_TIMESTAMP(%s) * 1000
#  AND s.created_at_ms <  UNIX_TIMESTAMP(%s) * 1000
#GROUP BY m.clue_id, s.created_at_ms
#ORDER BY clue_created_at ASC
#SQL
#export SQL_4
#
#PAYLOAD_4=$(python3 -c "
#import json, os
#print(json.dumps({
#    'requestId': 'test_grafana_query_004',
#    'appId': '2067518537974419456',
#    'data': {
#        'sql': os.environ['SQL_4'],
#        'params': [
#            '2026-07-28 00:00:00',
#            '2026-07-29 00:00:00',
#        ]
#    }
#}, ensure_ascii=False))
#")
#
#OUT_FILE_4="$(dirname "$0")/clue_conversation_history.txt"
#curl -s -X POST "$HOST/api/grafana/mysql/query" \
#  -H "Authorization: Bearer $TOKEN" \
#  -H "Content-Type: application/json" \
#  -d "$PAYLOAD_4" | python3 -c "
#import json, sys
#resp = json.load(sys.stdin)
#out_path = '$OUT_FILE_4'
#results = (resp.get('data') or {}).get('results') or []
#with open(out_path, 'w', encoding='utf-8') as f:
#    for row in results:
#        f.write('===== clue_id=' + str(row.get('clue_id')) + ' | created_at=' + str(row.get('clue_created_at')) + ' =====\n')
#        f.write('msg_count=' + str(row.get('msg_count')) + ', first=' + str(row.get('first_msg_time')) + ', last=' + str(row.get('last_msg_time')) + '\n')
#        f.write(str(row.get('conversation_history') or '') + '\n\n')
#print(f'共 {len(results)} 条会话，已写入 {out_path}')
#print(f'code={resp.get(\"code\")}, msg={resp.get(\"msg\")}')
#"
#echo ""


# 查询 clue_event_history
#echo "查询 clue_event_history:"
#curl -s -X POST "$HOST/api/grafana/query" \
#  -H "Authorization: Bearer $TOKEN" \
#  -H "Content-Type: application/json" \
#  -d '{
#    "requestId":"test_grafana_query_002",
#    "appId":"account_center",
#    "data":{
#      "sql":"SELECT clue_id, event_type, enter_time_ms FROM clue_event_history WHERE event_type IN (%s, %s) ORDER BY enter_time_ms DESC LIMIT %s",
#      "params":["pre_check_agent_start", "submit_agent_start", 5]
#    }
#  }' | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))"
#echo ""


# 非 SELECT 语句（应被拒绝）
#echo "非 SELECT 语句测试:"
#curl -s -X POST "$HOST/api/grafana/query" \
#  -H "Authorization: Bearer $TOKEN" \
#  -H "Content-Type: application/json" \
#  -d '{
#    "requestId":"test_grafana_query_003",
#    "appId":"account_center",
#    "data":{
#      "sql":"UPDATE clue_state SET processor = %s WHERE clue_id = %s",
#      "params":["agent", "test"]
#    }
#  }' | python3 -c "import json, sys; print(json.dumps(json.load(sys.stdin), indent=2, ensure_ascii=False))"
#echo ""
