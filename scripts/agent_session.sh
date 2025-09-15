#!/usr/bin/env bash
# 交互式多轮会话：预处理 Agent 外部脚本
# 使用与后端 external_runner 相同的脚本与参数规范
# 每轮从标准输入读取一段 Markdown（以单独一行的 %% 结束），调用
#   scripts/preprocess_agent_external.py
# 将结果回显到终端，并把输入/输出/命令写入 logs/queue 便于排查

set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs/queue"
SCRIPT_PY="$ROOT_DIR/scripts/preprocess_agent_external.py"
PY_BIN="${PY_BIN:-$(command -v python3 || command -v python)}"
mkdir -p "$LOG_DIR"

# 默认参数
AGENT_CONFIG=""
TOPIC_ID="demo"
MODE="note"
TIMEOUT="90"

usage() {
  cat <<USAGE
用法：
  $(basename "$0") [--agent-config 路径] [--topic-id ID] [--mode note|search|qa] [--timeout 秒]

示例：
  $(basename "$0") --agent-config config/agents/preprocess_structurer.deepseek_reasoner.json --topic-id t1 --mode note --timeout 90

输入约定：
  在提示符出现后逐行输入 Markdown，输入单独一行的 %% 表示该轮结束并开始处理。
  按 Ctrl+C 结束整个会话。
USAGE
}

# 解析参数
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent-config) AGENT_CONFIG="$2"; shift 2;;
    --topic-id) TOPIC_ID="$2"; shift 2;;
    --mode) MODE="$2"; shift 2;;
    --timeout) TIMEOUT="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "未知参数: $1"; usage; exit 1;;
  esac
done

if [[ -z "$PY_BIN" ]]; then
  echo "未找到 Python 解释器（python3/python）" >&2
  exit 1
fi
if [[ ! -f "$SCRIPT_PY" ]]; then
  echo "未找到脚本: $SCRIPT_PY" >&2
  exit 1
fi

printf "\n== 预处理会话开始 ==\n脚本: %s\nPython: %s\nTopic: %s\nMode: %s\nTimeout: %ss\nAgent: %s\n\n" \
  "$SCRIPT_PY" "$PY_BIN" "$TOPIC_ID" "$MODE" "$TIMEOUT" "${AGENT_CONFIG:-(无)}"

round=1
while true; do
  echo "---- 第 $round 轮 ----"
  echo "请输入 Markdown（以单独一行 %% 结束）："
  TMP_IN="$(mktemp)"
  while IFS= read -r line; do
    [[ "$line" == "%%" ]] && break
    printf "%s\n" "$line" >> "$TMP_IN"
  done

  OUT_FILE="$LOG_DIR/preprocess_cli.last_render.md"
  CMD_FILE="$LOG_DIR/preprocess_cli.last_cmd.txt"
  IN_FILE_COPY="$LOG_DIR/preprocess_cli.last_in.md"

  cp "$TMP_IN" "$IN_FILE_COPY" 2>/dev/null || true

  # 组合参数
  ARGS=("$SCRIPT_PY" --topic-id "$TOPIC_ID" --mode "$MODE" --timeout "$TIMEOUT" --input-file "$TMP_IN" --output-file "$OUT_FILE")
  if [[ -n "$AGENT_CONFIG" ]]; then
    ARGS+=(--agent-config "$AGENT_CONFIG")
  fi
  printf "%s %s\n" "$PY_BIN" "${ARGS[*]}" > "$CMD_FILE"

  # 执行
  set +e
  "$PY_BIN" "${ARGS[@]}"
  rc=$?
  set -e

  echo "[返回码] $rc"
  if [[ -f "$OUT_FILE" ]] && [[ -s "$OUT_FILE" ]]; then
    echo "[输出文件] $OUT_FILE"
    echo "========== 结果 =========="
    cat "$OUT_FILE"
    echo "\n=========================="
  else
    echo "[警告] 输出文件为空，尝试从 stdout/stderr 查看 logs/queue 下其他文件"
  fi

  rm -f "$TMP_IN"
  round=$((round+1))
  echo
done
