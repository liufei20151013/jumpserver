#!/bin/bash

set -e

# 检查 celery worker（队列名固定为 "celery"）
test -e /tmp/worker_ready_celery
test -e /tmp/worker_heartbeat_celery && test $(($(date +%s) - $(stat -c %Y /tmp/worker_heartbeat_celery))) -lt 20

# 检查 ansible worker（支持 "ansible" 以及端点路由的 "ansible_endpoint_*" 命名）
# 1. 至少存在一个 ready 文件
_ready_ok=false
for f in /tmp/worker_ready_ansible*; do
    if [ -e "$f" ]; then
        _ready_ok=true
        break
    fi
done
test "$_ready_ok" = true || (echo "No ansible worker ready file found" >&2; exit 1)

# 2. 至少存在一个心跳文件且在 20 秒内更新过
_heartbeat_ok=false
for f in /tmp/worker_heartbeat_ansible*; do
    if [ -e "$f" ] && [ $(($(date +%s) - $(stat -c %Y "$f"))) -lt 20 ]; then
        _heartbeat_ok=true
        break
    fi
done
test "$_heartbeat_ok" = true || (echo "No fresh ansible worker heartbeat found" >&2; exit 1)