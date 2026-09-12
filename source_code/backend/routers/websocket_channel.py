"""
WebSocket 实时推送通道
前端通过 WebSocket 连接接收：
  - 持仓状态变更（开仓/平仓/风控触发）
  - 实时行情推送
  - 风控告警
  - 策略评分更新
  - 审计日志事件

认证方式：
  - 登录用户: JWT token via query param ?token=xxx
  - 分享令牌: /ws/share/{share_token}
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Dict, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState

from backend.core.logging_config import logger

router = APIRouter()


class ConnectionManager:
    """WebSocket 连接管理器"""

    def __init__(self):
        self._user_connections: Dict[int, Set[WebSocket]] = {}
        self._share_connections: Dict[str, Set[WebSocket]] = {}
        self._broadcast: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect_user(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        async with self._lock:
            if user_id not in self._user_connections:
                self._user_connections[user_id] = set()
            self._user_connections[user_id].add(websocket)
        logger.info(f"[WS] 用户 {user_id} WebSocket 已连接")

    async def connect_share(self, websocket: WebSocket, share_token: str):
        await websocket.accept()
        async with self._lock:
            if share_token not in self._share_connections:
                self._share_connections[share_token] = set()
            self._share_connections[share_token].add(websocket)
        logger.info(f"[WS] 分享令牌 WebSocket 已连接")

    async def disconnect(self, websocket: WebSocket, user_id: int = None, share_token: str = None):
        async with self._lock:
            if user_id and user_id in self._user_connections:
                self._user_connections[user_id].discard(websocket)
                if not self._user_connections[user_id]:
                    del self._user_connections[user_id]
            if share_token and share_token in self._share_connections:
                self._share_connections[share_token].discard(websocket)
                if not self._share_connections[share_token]:
                    del self._share_connections[share_token]
            self._broadcast.discard(websocket)

    async def send_to_user(self, user_id: int, message: dict):
        """向指定用户的所有连接推送消息"""
        conns = self._user_connections.get(user_id, set())
        msg_text = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        for ws in conns:
            try:
                await ws.send_text(msg_text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    async def send_to_share(self, share_token: str, message: dict):
        """向指定分享令牌的所有连接推送消息"""
        conns = self._share_connections.get(share_token, set())
        msg_text = json.dumps(message, ensure_ascii=False, default=str)
        dead = []
        for ws in conns:
            try:
                await ws.send_text(msg_text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)

    async def broadcast(self, message: dict):
        """向所有连接广播"""
        msg_text = json.dumps(message, ensure_ascii=False, default=str)
        all_conns = list(self._broadcast)
        for uid, conns in self._user_connections.items():
            all_conns.extend(conns)
        for conns in self._share_connections.values():
            all_conns.extend(conns)
        dead = []
        for ws in all_conns:
            try:
                await ws.send_text(msg_text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._broadcast.discard(ws)

    def get_user_connection_count(self, user_id: int) -> int:
        return len(self._user_connections.get(user_id, set()))

    def get_total_connections(self) -> int:
        total = sum(len(s) for s in self._user_connections.values())
        total += sum(len(s) for s in self._share_connections.values())
        total += len(self._broadcast)
        return total


ws_manager = ConnectionManager()


# 消息构建辅助
def make_message(msg_type: str, data: dict) -> dict:
    return {
        "type": msg_type,
        "data": data,
        "timestamp": datetime.utcnow().isoformat(),
    }


# 同步推送接口（供定时任务/回调调用）
def push_to_user(user_id: int, msg_type: str, data: dict):
    """从同步上下文向用户推送消息（线程安全）"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(
                ws_manager.send_to_user(user_id, make_message(msg_type, data))
            )
    except RuntimeError:
        pass  # 无事件循环，跳过


def push_position_update(user_id: int, position_data: dict):
    push_to_user(user_id, "position_update", position_data)


def push_risk_alert(user_id: int, alert_data: dict):
    push_to_user(user_id, "risk_alert", alert_data)


def push_trade_log(user_id: int, log_data: dict):
    push_to_user(user_id, "trade_log", log_data)


# WebSocket 端点
@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """登录用户 WebSocket 端点"""
    user_id = None
    try:
        if token:
            try:
                from backend.core.auth import decode_token
                payload = decode_token(token)
                user_id = payload.get("uid") or payload.get("sub")
                if user_id:
                    user_id = int(user_id)
            except Exception:
                await websocket.accept()
                await websocket.send_text(json.dumps({"type": "error", "data": "认证失败"}))
                await websocket.close()
                return

        if not user_id:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "data": "缺少token"}))
            await websocket.close()
            return

        await ws_manager.connect_user(websocket, user_id)
        await websocket.send_text(json.dumps({
            "type": "connected",
            "data": {"user_id": user_id},
            "timestamp": datetime.utcnow().isoformat(),
        }, ensure_ascii=False))

        # 心跳循环
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data) if data else {}
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS] 连接异常: {e}")
    finally:
        if user_id:
            await ws_manager.disconnect(websocket, user_id=user_id)
        logger.info(f"[WS] 用户 {user_id} 连接已断开")


@router.websocket("/ws/share/{share_token}")
async def websocket_share_endpoint(
    websocket: WebSocket,
    share_token: str,
):
    """分享令牌 WebSocket 端点（免登录，通过 share_token 认证）"""
    # 验证 share_token
    from backend.services.monitor_service import validate_share_token
    token_data = validate_share_token(share_token)
    if not token_data:
        await websocket.accept()
        await websocket.send_text(json.dumps({"type": "error", "data": "无效或过期的分享令牌"}))
        await websocket.close()
        return

    await ws_manager.connect_share(websocket, share_token)
    await websocket.send_text(json.dumps({
        "type": "connected",
        "data": {"share_token": share_token[:8] + "..."},
        "timestamp": datetime.utcnow().isoformat(),
    }, ensure_ascii=False))

    try:
        while True:
            try:
                data = await websocket.receive_text()
                msg = json.loads(data) if data else {}
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"[WS] 分享连接异常: {e}")
    finally:
        await ws_manager.disconnect(websocket, share_token=share_token)
        logger.info(f"[WS] 分享令牌连接已断开")
