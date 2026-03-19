import feedparser
import requests
import json
import time
from datetime import datetime, timedelta

# ================= 配置区 (请修改这里) =================
# 1. 企业微信自建应用配置
WECOM_CID = "ww2de30f4164f46c2d"      # 填入企业ID
WECOM_SECRET = "Jj7dBm6XcJ1MKmZX57_WRVrQD2SQGDWWuXo9IHFxM9I" # 填入应用Secret
WECOM_AID = "1000011"                 # 填入AgentId

# 2. AI 配置 (DeepSeek / Kimi / GPT)
AI_API_KEY = "sk-M2CYfsOWeHg18o22vMUQ3uKnMsuiWKsH9qBq07UIlPDBv80Q"
AI_API_URL = "https://www.dmxapi.cn/v1/chat/completions"

# 3. 订阅源配置 (保持不变，指向本地服务)
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
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={WECOM_CID}&corpsecret={WECOM_SECRET}"
    try:
        resp = requests.get(url)
        data = resp.json()
        if data.get("errcode") == 0:
            return data.get("access_token")
        else:
            print(f"Token获取失败: {data}")
            return None
    except Exception as e:
        print(f"Token网络错误: {e}")
        return None

def send_wecom_app(content):
    """通过自建应用发送 Markdown 消息"""
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
            print("✅ 推送成功！")
        else:
            print(f"❌ 推送失败: {res_data}")
    except Exception as e:
        print(f"推送网络错误: {e}")

def get_ai_summary(text):
    """AI 摘要逻辑 (保持不变)"""
    if not text: return "无内容"
    headers = {"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": "DeepSeek-V3.2",
        "messages": [
            {"role": "system", "content": "你是一个营销情报官。请将新闻总结为一句话(50字内)，包含事实与对营销行业的影响。"},
            {"role": "user", "content": text[:800]} 
        ]
    }
    try:
        resp = requests.post(AI_API_URL, json=payload, headers=headers, timeout=10)
        return resp.json()['choices'][0]['message']['content']
    except Exception as e:
        print(f"AI Error: {e}")
        return "摘要生成超时"

def run_task():
    print(f"开始任务: {datetime.now()}")
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
                print(f"Error fetching {url}: {e}")
                
        if cat_content:
            report += f"\n## {category}\n{cat_content}"
            
    if has_update:
        send_wecom_app(report)
    else:
        print("今日无更新，不推送")

if __name__ == "__main__":
    run_task()


