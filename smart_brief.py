import feedparser
import requests
import json
import time
from datetime import datetime, timedelta
import os
import urllib.parse
import logging
from logging.handlers import TimedRotatingFileHandler

# 伪装浏览器，防止部分 RSS 源的反爬拦截
feedparser.USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"

# ================= 日志系统配置 =================
LOG_FILE = '/root/marketing_bot/bot.log'
logger = logging.getLogger('MIABot')
logger.setLevel(logging.INFO)

if not logger.handlers:
    file_handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=30, encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

CONFIG_FILE = '/root/marketing_bot/config.json'
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    CONFIG = json.load(f)

# ================= 工具函数 =================

def get_access_token():
    url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={CONFIG['wecom']['cid']}&corpsecret={CONFIG['wecom']['secret']}"
    try:
        return requests.get(url).json().get("access_token")
    except Exception as e:
        logger.error(f"获取 Token 失败: {e}")
        return None

def send_wecom(content):
    token = get_access_token()
    if not token: return
    url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
    payload = {
        "touser": "@all",
        "msgtype": "markdown",
        "agentid": CONFIG['wecom']['aid'],
        "markdown": {"content": content},
        "safe": 0
    }
    requests.post(url, json=payload)

def fetch_from_search_api(keywords, category_name):
    """
    【独立功能模块：全网关键词泛搜】
    当前状态：休眠 (Disabled)
    未来展望：预留给更稳定的企业级舆情API（如天行数据、微信公众号官方API等）。
    """
    if not keywords:
        return []
    # logger.debug(f"🔍 关键词搜索模块已触发，但当前处于休眠状态，跳过抓取: {keywords}")
    candidates = []
    # ==========================================
    # 未来如果有可行的搜索代码，直接写在这里面
    # ==========================================
    return candidates

def ai_process_category(category_name, news_list, category_prompt=""):
    if not news_list: return None
    
    input_text = f"【当前处理板块】：{category_name}\n【待筛选列表】：\n"
    for i, news in enumerate(news_list):
        clean_title = news['title'].replace('\n', ' ')
        input_text += f"{i+1}. {clean_title} (Link: {news['link']})\n"

    final_system_prompt = CONFIG['ai']['system_prompt']
    if category_prompt:
        final_system_prompt += f"\n\n【本板块专属内容标准】：\n{category_prompt}"

    # 💡 植入不可违抗的“最高指令” (解决废话和丢链接问题)
    final_system_prompt += """\n\n【系统最高强制指令】(覆盖上述所有规则)：
1. 宁缺毋滥：如果列表里没有任何符合标准的新闻，你必须、且只能回复四个英文字母：NONE。绝对不允许向用户解释原因，不允许说任何多余的话！
2. 格式红线：只要你输出了新闻摘要，标题必须严格包含原文URL，使用格式：### [重写后的精简标题](原文Link)。绝对不允许丢失链接！"""

    headers = {"Authorization": f"Bearer {CONFIG['ai']['api_key']}", "Content-Type": "application/json"}
    payload = {
        "model": CONFIG['ai']['model'],
        "messages": [
            {"role": "system", "content": final_system_prompt},
            {"role": "user", "content": input_text[:15000]}
        ],
        "temperature": 0.1 # 💡 调低发散性，让AI变成无情的执行机器
    }
    
    logger.info(f"🤖 开始呼叫 AI 分析 [{category_name}] (共 {len(news_list)} 条信源喂给AI)")
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(CONFIG['ai']['api_url'], json=payload, headers=headers, timeout=120)
            result_text = resp.json()['choices'][0]['message']['content'].strip()
            
            # 💡 在这里拦截 AI 的白卷
            if result_text == "NONE" or "NONE" in result_text:
                logger.info(f"🈳 AI 判定 [{category_name}] 无合格内容，已拦截。")
                return None
                
            return result_text
        except Exception as e:
            logger.warning(f"⚠️ AI 分析第 {attempt + 1} 次尝试失败 [{category_name}]: {e}")
            if attempt < max_retries - 1:
                time.sleep(5)
            else:
                logger.error(f"❌ AI 分析彻底失败 [{category_name}]")
                return None

# ================= 主流程 =================

def run_task():
    logger.info("="*40)
    logger.info(f"🚀 === 营销情报抓取任务开始 ===")
    logger.info("="*40)
    settings = CONFIG.get('settings', {})
    
    today_str = datetime.now().strftime('%m-%d')
    title_template = settings.get('report_title', '📅 营销情报早报 | {date}')
    header_msg = f"# {title_template.replace('{date}', today_str)}\n> 正在为您通过 AI 融合检索定向信源与全网热词..."
    send_wecom(header_msg)
    
    has_any_update = False
    
    for category, feed_data in CONFIG.get('feeds', {}).items():
        logger.info(f"\n📁 正在处理板块: 【{category}】")
        category_candidates = []
        
        # --- A. 抓取定向 RSS ---
        rss_urls = feed_data.get('rss', [])
        for raw_url in rss_urls:
            url = raw_url.split('#')[0].strip()
            if not url: continue
            try:
                feed = feedparser.parse(url)
                valid_count = 0
                for entry in feed.entries:
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        dt = datetime.fromtimestamp(time.mktime(entry.published_parsed))
                        if datetime.now() - dt > timedelta(hours=24): continue
                    
                    category_candidates.append({"title": f"[RSS] {entry.title}", "link": entry.link})
                    valid_count += 1
                    logger.info(f"  📥 抓取命中 -> {entry.title} ({entry.link})")
                
                logger.info(f"✅ RSS源 [{url}] 抓取完成，共获得 {valid_count} 条有效资讯")
            except Exception as e:
                logger.error(f"⚠️ RSS抓取失败 [{url}]: {e}")

        # --- B. 抓取全网关键词 (预留接口，当前休眠) ---
        keywords = feed_data.get('keywords', [])
        if keywords:
            search_results = fetch_from_search_api(keywords, category)
            category_candidates.extend(search_results)

        # --- C. 合并、排重与 AI 筛选 ---
        if category_candidates:
            seen_links = set()
            unique_candidates = []
            for item in category_candidates:
                if item['link'] not in seen_links:
                    unique_candidates.append(item)
                    seen_links.add(item['link'])
            
            logger.info(f"⏳ 板块 【{category}】 排重后剩余 {len(unique_candidates)} 条数据交由 AI 筛选...")
            ai_summary = ai_process_category(category, unique_candidates, feed_data.get('prompt', ''))            

            if ai_summary:
                msg_body = f"## {category}\n{ai_summary}"
                logger.info(f"📤 推送板块 【{category}】 成功")
                send_wecom(msg_body)
                has_any_update = True
                time.sleep(2)
        else:
            logger.info(f"📭 板块 【{category}】 今日无更新数据")

    if has_any_update:
        if settings.get('show_footer', True):
            send_wecom(f"\n{settings.get('footer_text', '')}")
        logger.info("✅ 任务圆满完成")
    else:
        empty_msg = settings.get('empty_message', '📭 今日全网无重要更新。')
        send_wecom(empty_msg)
        logger.info("📭 今日全网无更新内容被推送")

if __name__ == "__main__":
    run_task()
