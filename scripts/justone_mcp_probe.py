#!/usr/bin/env python3
"""JustOneAPI MCP 只读体检脚本。

用途：在发任何付费调用前，确认 MCP 连通性、账户余额与端点契约。
只调用免费工具（initialize / tools list / list_platforms /
search_endpoints / get_endpoint_schema / get_account_balance /
get_usage_summary），**绝不调用 call_endpoint**。

令牌来源（按优先级）：
  1. --token <值>            或环境变量 JUSTONEAPI_MCP_TOKEN
  2. --from-codex-keychain   读 macOS 钥匙串里 Codex 存的 JustOneAPI OAuth 凭证

注意：--from-codex-keychain 只读，不做刷新。Codex 的 access_token 寿命约 1 小时
（expires_in 3599）；过期时它会返回 401，此时改用 --token 从控制台取 API Token。
刻意不实现 refresh_token 刷新——那会轮换掉 Codex 正在使用的刷新令牌，
可能让 Codex 侧本就可用的 MCP 失效。
"""

import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

MCP_URL = "https://mcp.justoneapi.com/mcp"
KEYCHAIN_SERVICE = "Codex MCP Credentials"
KEYCHAIN_ACCOUNT_PREFIX = "justoneapi|"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")

FREE_TOOLS = ("list_platforms", "get_account_balance", "get_usage_summary",
              "search_endpoints", "get_endpoint_schema")
PAID_TOOLS = ("call_endpoint",)


def _codex_mcp_accounts():
    """列出钥匙串中 Codex 存过的 JustOneAPI MCP 账号名。

    转储按记录组织，每条记录以 keychain: 行开头；属性顺序不固定，
    因此按记录切分再匹配，不做行序假设。
    """
    out = subprocess.run(
        ["security", "dump-keychain"], capture_output=True, text=True
    ).stdout
    records, current = [], []
    for line in out.splitlines():
        if line.startswith("keychain:"):
            if current:
                records.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        records.append(current)

    found = []
    for record in records:
        svce = acct = None
        for line in record:
            text = line.strip()
            for key in ("svce", "acct"):
                prefix = f'"{key}"<blob>='
                if text.startswith(prefix) and '="' in text:
                    value = text.split('="', 1)[1].rstrip('"')
                    if key == "svce":
                        svce = value
                    else:
                        acct = value
        if svce == KEYCHAIN_SERVICE and acct and acct.startswith(KEYCHAIN_ACCOUNT_PREFIX):
            found.append(acct)
    return found


def token_from_codex_keychain():
    accounts = _codex_mcp_accounts()
    if not accounts:
        raise SystemExit(
            "钥匙串中未找到 Codex 的 JustOneAPI 凭证。"
            "请改用 --token 或环境变量 JUSTONEAPI_MCP_TOKEN。"
        )
    raw = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE,
         "-a", accounts[0], "-w"],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(raw)["token_response"]["access_token"]


class Client:
    """最小 streamable-http MCP 客户端（只读）。"""

    def __init__(self, token):
        self.token = token
        self.sid = None
        self._id = 0

    def _post(self, method, params=None, notify=False):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self._id
        if params is not None:
            body["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": UA,
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        if self.sid:
            headers["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(
            MCP_URL, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                sid = resp.headers.get("Mcp-Session-Id")
                if sid:
                    self.sid = sid
                return resp.status, resp.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", "ignore")

    @staticmethod
    def _parse(raw):
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
        events = [json.loads(l[5:].strip())
                  for l in raw.splitlines() if l.startswith("data:")]
        return events[0] if len(events) == 1 else events

    def handshake(self):
        status, raw = self._post("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "justone-probe", "version": "1.0"},
        })
        if status != 200:
            raise SystemExit(
                f"initialize 失败 HTTP {status}：{raw[:300]}\n"
                "若为 401，说明令牌无效或已过期（Codex 的 OAuth 令牌寿命约 1 小时）。\n"
                "若含 Cloudflare error 1010，说明请求指纹被拦，需带浏览器 UA。"
            )
        self._post("notifications/initialized", {}, notify=True)
        return self._parse(raw)["result"]

    def call_free(self, tool, args=None):
        if tool in PAID_TOOLS:
            raise SystemExit(f"拒绝调用付费工具 {tool}")
        if tool not in FREE_TOOLS:
            raise SystemExit(f"未加白名单的工具 {tool}")
        status, raw = self._post("tools/call", {"name": tool, "arguments": args or {}})
        if status != 200:
            raise RuntimeError(f"{tool} HTTP {status}: {raw[:300]}")
        payload = self._parse(raw)
        for part in payload.get("result", {}).get("content", []):
            if part.get("type") == "text":
                return part["text"]
        return json.dumps(payload)[:1000]


def main():
    ap = argparse.ArgumentParser(description="JustOneAPI MCP 只读体检")
    ap.add_argument("cmd", choices=["ping", "balance", "usage", "platforms",
                                    "endpoints", "schema"])
    ap.add_argument("arg", nargs="?", help="endpoints 的查询词 / schema 的 endpoint_id")
    ap.add_argument("--token")
    ap.add_argument("--from-codex-keychain", action="store_true")
    ap.add_argument("--platform")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    token = args.token or os.environ.get("JUSTONEAPI_MCP_TOKEN")
    if not token and args.from_codex_keychain:
        token = token_from_codex_keychain()
    if not token:
        raise SystemExit("缺少令牌：用 --token、JUSTONEAPI_MCP_TOKEN 或 --from-codex-keychain")

    client = Client(token)
    info = client.handshake()

    if args.cmd == "ping":
        print(f"MCP 连通 · server={info['serverInfo']['name']} "
              f"v{info['serverInfo']['version']} · protocol={info['protocolVersion']}")
        return

    if args.cmd == "balance":
        text = client.call_free("get_account_balance")
        data = json.loads(text)["data"]
        print(f"余额 {data['availableBalance']} {data['currency']}"
              f"（预留 {data['reservedAmount']}）")
        if args.json:
            print(text)
        return

    if args.cmd == "usage":
        text = client.call_free("get_usage_summary")
        data = json.loads(text)["data"]
        tok = data["token"]
        print(f"令牌 {tok['name']} · 状态 {tok['status']} · 默认令牌 {tok['defaultToken']}")
        print(f"预算上限 {tok['budgetAmount']} · 已用 {tok['usedAmount']} · "
              f"累计消费 {data['totalAmount']} {data['currency']}")
        if tok["budgetAmount"] is None:
            print("⚠ 未设预算上限，建议在控制台设置以防超支")
        return

    if args.cmd == "platforms":
        text = client.call_free("list_platforms")
        data = json.loads(text)
        print(f"平台 {len(data['platforms'])} 个 · 端点 {data['endpoint_count']} 个")
        for p in data["platforms"]:
            print(f"  {p['id']:<18} {p['endpoint_count']:>3}  {p['name']}")
        return

    if args.cmd == "endpoints":
        if not args.arg:
            raise SystemExit("endpoints 需要查询词，例如：endpoints 小红书笔记搜索")
        params = {"query": args.arg, "limit": args.limit}
        if args.platform:
            params["platform"] = args.platform
        text = client.call_free("search_endpoints", params)
        data = json.loads(text)
        print(f"置信度 {data['confidence']} · 命中 {len(data['results'])} 条")
        for r in data["results"]:
            print(f"  {r['endpoint_id']:<34} {r['title']} "
                  f"(必填 {','.join(r['required_params']) or '无'})")
            for alt in r.get("alternatives") or []:
                mark = "推荐" if alt.get("recommended") else "备选"
                print(f"      ↳ {mark} {alt['endpoint_id']}")
        return

    if args.cmd == "schema":
        if not args.arg:
            raise SystemExit("schema 需要 endpoint_id，例如：schema xiaohongshu.search_note_v4")
        print(client.call_free("get_endpoint_schema", {"endpoint_id": args.arg})[:4000])


if __name__ == "__main__":
    main()
