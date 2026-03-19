import feedparser
import requests
import json
import time
import os
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta

# ================= 配置区 =================
# 说明：不要在代码里硬编码密钥。请使用环境变量：
# - WECOM_CID / WECOM_SECRET / WECOM_AID
# - AI_API_KEY / AI_API_URL / AI_MODEL
#
# 可选：如果存在 ./config.json，且包含 wecom/ai 字段，也会作为 fallback。

def _load_local_config():
    try:
        with open("config.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

_CFG = _load_local_config()

# ================= 日志：每日轮转（写入 logs/） =================
def _default_bot_dir() -> str:
    env_dir = os.getenv("MARKETING_BOT_DIR")
    if env_dir:
        return env_dir
    if os.path.isdir("/root/marketing_bot"):
        return "/root/marketing_bot"
    return os.path.abspath(os.path.dirname(__file__))


_BOT_DIR = _default_bot_dir()
_LOGS_DIR = os.getenv("LOGS_DIR", os.path.join(_BOT_DIR, "logs"))
os.makedirs(_LOGS_DIR, exist_ok=True)
_DAILY_LOG_FILE = os.getenv("DAILY_LOG_FILE", os.path.join(_LOGS_DIR, "daily_brief.log"))

logger = logging.getLogger("DailyBrief")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    _fh = TimedRotatingFileHandler(_DAILY_LOG_FILE, when="midnight", interval=1, backupCount=30, encoding="utf-8")
    _fh.setFormatter(_fmt)
    logger.addHandler(_fh)
    _ch = logging.StreamHandler()
    _ch.setFormatter(_fmt)
    logger.addHandler(_ch)

# 1. 企业微信自建应用配置
WECOM_CID = (os.getenv("WECOM_CID") or _CFG.get("wecom", {}).get("cid") or "").strip()
WECOM_SECRET = (os.getenv("WECOM_SECRET") or _CFG.get("wecom", {}).get("secret") or "").strip()
WECOM_AID = (os.getenv("WECOM_AID") or _CFG.get("wecom", {}).get("aid") or "").strip()

# 2. AI 配置 (DeepSeek / Kimi / GPT)
AI_API_KEY = (os.getenv("AI_API_KEY") or _CFG.get("ai", {}).get("api_key") or "").strip()
AI_API_URL = (os.getenv("AI_API_URL") or _CFG.get("ai", {}).get("api_url") or "").strip()
AI_MODEL = (os.getenv("AI_MODEL") or _CFG.get("ai", {}).get("model") or "DeepSeek-V3.2").strip()

# 3. 订阅源配置 (指向本地服务)
FEEDS = {
    "📢 政策导向": [
        "http://localhost:1200/gov/policy/latest",
        "http://localhost:1200/cac/new"
    ],
    "📱 社交动态": [
        "http://localhost:4000/feeds/all.atom" # 填入 WeWe RSS 后台生成的链接
    ],
    "💡 营销行业": [
        "http://localhost:1200/socialbeta",
        "http://localhost:1200/36kr/motif/327685836801"
    ],
    "🤖 AI工具": [
        "http://localhost:1200/jike/topic/6360f06567220e3633215234"
    ]
}
# ======================================================

def get_access_token():
    """获取企业微信 Access Token"""
    if not (WECOM_CID and WECOM_SECRET):
        logger.error("缺少企业微信配置：请设置 WECOM_CID / WECOM_SECRET（或在 config.json 的 wecom 中提供）")
        return None
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CID}&corpsecret={WECOM_SECRET}"
    try:
        resp = requests.get(url)
        data = resp.json()
        if data.get("errcode") == 0:
            return data.get("access_token")
        else:
            logger.error(f"Token获取失败: {data}")
            return None
    except Exception as e:
        logger.error(f"Token网络错误: {e}")
        return None

def send_wecom_app(content):
    """通过自建应用发送 Markdown 消息"""
    if not WECOM_AID:
        logger.error("缺少企业微信配置：请设置 WECOM_AID（或在 config.json 的 wecom 中提供）")
        return
    token = get_access_token()
    if not token:
        return

    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    
    # 构造消息体
    payload = {
        "touser": "@all",  # @all 表示发送给该应用可见范围内的所有人
        "msgtype": "markdown",
        "agentid": WECOM_AID,
        "markdown": {
            "content": content
        },
        "safe": 0
    }
    
    try:
        resp = requests.post(url, json=payload)
        res_data = resp.json()
        if res_data.get("errcode") == 0:
            logger.info("✅ 推送成功！")
        else:
            logger.error(f"❌ 推送失败: {res_data}")
    except Exception as e:
        logger.error(f"推送网络错误: {e}")

def get_ai_summary(text):
    """AI 摘要逻辑 (保持不变)"""
    if not text: return "无内容"
    if not (AI_API_KEY and AI_API_URL):
        return "缺少 AI 配置：请设置 AI_API_KEY / AI_API_URL（或在 config.json 的 ai 中提供）"
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content": "你是一个营销情报官。请将新闻总结为一句话(50字内)，包含事实与对营销行业的影响。"},
            {"role": "user", "content": text[:800]} 
        ]
    }
    try:
        resp = requests.post(AI_API_URL, json=payload, headers=headers, timeout=10)
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return "摘要生成超时"

def run_task():
    logger.info(f"开始任务: {datetime.now()}")
    report = f"# 📅 营销早报 | {datetime.now().strftime('%m-%d')}\n"
    has_update = False
    
    for category, urls in FEEDS.items():
        cat_content = ""
        for url in urls:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries:
                    # 时间过滤逻辑 (24小时内)
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if datetime.now() - dt > timedelta(hours=24):
                            continue
                    
                    summary = get_ai_summary(entry.get('summary', '') or entry.title)
                    cat_content += f"> **[{entry.title}]({entry.link})**\n> <font color='comment'>{summary}</font>\n\n"
                    has_update = True
                    if len(cat_content) > 1000: break 
            except Exception as e:
                logger.warning(f"Error fetching {url}: {e}")
                
        if cat_content:
            report += f"\n## {category}\n{cat_content}"
            
    if has_update:
        send_wecom_app(report)
    else:
        logger.info("今日无更新，不推送")

if __name__ == "__main__":
    run_task()


