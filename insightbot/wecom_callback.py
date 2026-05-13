"""
WeChat Work (WeCom) callback handler.

Handles URL verification and encrypted message receiving from WeChat Work.
Runs as a lightweight HTTP server.

Usage:
    from insightbot.wecom_callback import start_webhook_server
    start_webhook_server(port=8080)

Environment variables:
    WECOM_TOKEN          — Callback verification token
    WECOM_ENCODING_AES_KEY — AES key for message decryption (43 chars)
    WECOM_CID            — Corp ID
    WECOM_SECRET         — App secret
    WECOM_AGENT_ID       — Agent ID
"""

import hashlib
import json
import logging
import os
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Callable

from .channels import send_to_channel
from .scheduler import Scheduler, create_scheduler

logger = logging.getLogger("WeComWebhook")


# ---------------------------------------------------------------------------
# Crypto helpers
# ---------------------------------------------------------------------------

def _decode_aes_key(aes_key_b64: str) -> bytes:
    import base64
    return base64.b64decode(aes_key_b64 + "=")


def _aes_decrypt(ciphertext: bytes, aes_key: bytes) -> bytes:
    from Crypto.Cipher import AES

    iv = aes_key[:16]
    cipher = AES.new(aes_key, AES.MODE_CBC, iv)
    decrypted = cipher.decrypt(ciphertext)
    # PKCS#7 unpadding
    pad_len = decrypted[-1]
    return decrypted[:-pad_len]


def _decrypt_wecom_msg(encrypted: str, aes_key_b64: str) -> str:
    import base64

    aes_key = _decode_aes_key(aes_key_b64)
    ciphertext = base64.b64decode(encrypted)
    decrypted = _aes_decrypt(ciphertext, aes_key)
    # Format: random(16) + msg_len(4) + msg + appid
    msg_len = int.from_bytes(decrypted[16:20], byteorder="big")
    msg = decrypted[20 : 20 + msg_len].decode("utf-8")
    return msg


def _verify_signature(token: str, timestamp: str, nonce: str, encrypted: str) -> str:
    """Return SHA1 signature for WeChat Work callback verification."""
    data = sorted([token, timestamp, nonce, encrypted])
    return hashlib.sha1("".join(data).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Command dispatcher
# ---------------------------------------------------------------------------

def _reply_text(to_user: str, from_user: str, content: str) -> str:
    """Build a plaintext XML reply (for testing without encryption)."""
    return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>0</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""


def _handle_command(cmd: str, scheduler: Scheduler, channel_id: str | None) -> str:
    """Parse command and return reply text."""
    cmd = cmd.strip().lower()
    parts = cmd.split()
    if not parts:
        return "收到空指令，输入 help 查看可用命令。"

    action = parts[0]

    if action in ("help", "帮助"):
        return (
            "可用命令:\n"
            "  help       — 显示帮助\n"
            "  status     — 查看任务状态\n"
            "  list       — 列出所有任务\n"
            "  run <id>   — 立即运行指定任务\n"
            "  dry <id>   — 试运行指定任务（不发消息）"
        )

    if action in ("status", "状态"):
        enabled = [t.task_id for t in scheduler.tasks.values() if t.enabled]
        return f"当前共 {len(scheduler.tasks)} 个任务，其中 {len(enabled)} 个已启用。"

    if action in ("list", "列表"):
        lines = []
        for tid, task in scheduler.tasks.items():
            flag = "●" if task.enabled else "○"
            lines.append(f"{flag} {tid}: {task.name}")
        return "任务列表:\n" + "\n".join(lines) if lines else "暂无任务。"

    if action in ("run", "执行"):
        if len(parts) < 2:
            return "用法: run <task_id>"
        task_id = parts[1]
        try:
            result = scheduler.run_task_by_id(task_id, dry_run=False)
            ok = result.get("ok", False)
            return f"任务 '{task_id}' 执行{'成功' if ok else '失败'}。"
        except Exception as e:
            return f"执行任务失败: {e}"

    if action in ("dry", "试运行"):
        if len(parts) < 2:
            return "用法: dry <task_id>"
        task_id = parts[1]
        try:
            result = scheduler.run_task_by_id(task_id, dry_run=True)
            ok = result.get("ok", False)
            md_preview = result.get("final_markdown", "")[:200]
            return f"任务 '{task_id}' 试运行{'成功' if ok else '失败'}。\n预览:\n{md_preview}..."
        except Exception as e:
            return f"试运行失败: {e}"

    return f"未知命令: {action}。输入 help 查看可用命令。"


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------

def make_request_handler(
    token: str,
    aes_key: str,
    scheduler: Scheduler,
    channel_id: str | None = None,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:
            logger.info(fmt % args)

        def do_GET(self) -> None:
            """Handle WeChat Work URL verification."""
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            signature = qs.get("msg_signature", [""])[0]
            timestamp = qs.get("timestamp", [""])[0]
            nonce = qs.get("nonce", [""])[0]
            echostr = qs.get("echostr", [""])[0]

            expected = _verify_signature(token, timestamp, nonce, echostr)
            if signature != expected:
                logger.warning("Signature mismatch — possible fake request")
                self.send_response(403)
                self.end_headers()
                return

            # Decrypt echostr and return plaintext
            if aes_key:
                try:
                    plaintext = _decrypt_wecom_msg(echostr, aes_key)
                except Exception as e:
                    logger.warning(f"Failed to decrypt echostr: {e}")
                    plaintext = echostr
            else:
                plaintext = echostr

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(plaintext.encode())

        def do_POST(self) -> None:
            """Handle incoming messages."""
            from urllib.parse import parse_qs, urlparse

            qs = parse_qs(urlparse(self.path).query)
            signature = qs.get("msg_signature", [""])[0]
            timestamp = qs.get("timestamp", [""])[0]
            nonce = qs.get("nonce", [""])[0]

            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            # Parse XML
            try:
                root = ET.fromstring(body)
                encrypt_node = root.find("Encrypt")
                encrypted = encrypt_node.text if encrypt_node is not None else ""
            except ET.ParseError:
                logger.warning("Invalid XML received")
                self.send_response(400)
                self.end_headers()
                return

            # Verify signature
            expected = _verify_signature(token, timestamp, nonce, encrypted)
            if signature != expected:
                logger.warning("Signature mismatch on POST")
                self.send_response(403)
                self.end_headers()
                return

            # Decrypt message
            if not aes_key:
                logger.warning("No AES key configured — cannot decrypt message")
                self.send_response(500)
                self.end_headers()
                return

            try:
                plaintext = _decrypt_wecom_msg(encrypted, aes_key)
                msg_root = ET.fromstring(plaintext)
                msg_type = msg_root.find("MsgType")
                content_node = msg_root.find("Content")
                from_user_node = msg_root.find("FromUserName")
                to_user_node = msg_root.find("ToUserName")

                msg_type_text = msg_type.text if msg_type is not None else ""
                content = content_node.text if content_node is not None else ""
                from_user = from_user_node.text if from_user_node is not None else ""
                to_user = to_user_node.text if to_user_node is not None else ""
            except Exception as e:
                logger.warning(f"Failed to decrypt/parse message: {e}")
                self.send_response(200)
                self.end_headers()
                return

            if msg_type_text == "text" and content:
                logger.info(f"Received command from {from_user}: {content}")
                reply = _handle_command(content, scheduler, channel_id)

                # Reply via channel if configured, otherwise return empty success
                if channel_id:
                    try:
                        send_to_channel(channel_id, reply)
                    except Exception as e:
                        logger.error(f"Failed to send reply: {e}")

            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"success")

    return Handler


# ---------------------------------------------------------------------------
# Server entrypoint
# ---------------------------------------------------------------------------

def start_webhook_server(
    port: int = 8080,
    scheduler: Scheduler | None = None,
    channel_id: str | None = None,
) -> None:
    """Start the WeChat Work webhook server."""
    token = os.getenv("WECOM_TOKEN", "")
    aes_key = os.getenv("WECOM_ENCODING_AES_KEY", "")

    if not token:
        logger.warning("WECOM_TOKEN not set — signature verification will fail")

    scheduler = scheduler or create_scheduler()
    handler = make_request_handler(token, aes_key, scheduler, channel_id)

    server = HTTPServer(("", port), handler)
    logger.info(f"WeCom webhook server listening on port {port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down webhook server")
        server.shutdown()
