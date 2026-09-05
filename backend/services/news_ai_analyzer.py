"""
新闻AI增强分析模块（关键词预筛选 + 多API轮询）
- 关键词预筛选：只对命中重要关键词的新闻调AI，节省90%+成本
- 去重：已AI分析过的新闻自动跳过
- 多API轮询：失败自动切换
"""
import json
import traceback
from datetime import datetime, timedelta
from typing import Optional, List, Dict

from sqlalchemy.orm import Session

from backend.core.logging_config import logger
from backend.core.security import decrypt_api_key
from backend.models.analytics import NewsArticle
from backend.models.user import User
from backend.models.system_config import SystemConfig
from backend.services.news_keywords import pre_filter_news


def _is_important_news(article: NewsArticle) -> bool:
    """关键词预筛选：判断是否需要AI深度分析"""
    result = pre_filter_news(article.title, article.summary or "")
    return result["need_ai"]


def _build_analysis_prompt(article: NewsArticle) -> str:
    """构建AI分析提示词"""
    return f"""你是专业的金融新闻分析师。请分析以下新闻对加密货币和商品市场的影响。

新闻标题：{article.title}
新闻摘要：{article.summary or article.content[:500]}
新闻来源：{article.source_name}
发布时间：{article.published_at}

请用JSON格式输出分析结果（不要输出其他内容）：
{{
    "sentiment": "positive/negative/neutral",
    "sentiment_score": -1.0到1.0之间的数字,
    "impact_level": 1到4的数字,
    "affected_symbols": ["BTC", "ETH", "SOL", "XAU", "WTI", "SKHYNIX", "SNDK", "SAND", "HBAR"],
    "direction": "bullish/bearish/neutral",
    "buy_sell_signal": "buy/sell/hold",
    "confidence": 0到100的数字,
    "summary": "一句话中文摘要",
    "key_factors": ["关键因素1", "关键因素2"]
}}"""

ANALYSIS_SYSTEM_PROMPT = """你是专业的金融新闻分析师，擅长分析新闻对加密货币(BTC/ETH/SOL)、黄金(XAU)、原油(WTI)、美股(TSLA/NVDA/AAPL/MSFT/TCEHY)、半导体股票(SKHYNIX-海力士/SNDK-闪迪)的影响。
你的分析结果将用于量化交易系统的新闻情绪评分（占总评分30%权重）。

分析原则：
1. 非农数据好于预期 → 利空加密货币和黄金（美元走强）
2. 加息/鹰派 → 利空加密货币和黄金
3. 降息/鸽派 → 利多加密货币和黄金
4. 战争/地缘冲突 → 利多黄金和原油（避险需求）
5. ETF通过 → 利多对应币种
6. 黑客/交易所暴雷 → 利空对应币种
7. OPEC减产 → 利多原油
8. 制裁 → 利多加密货币（避险替代品）

只输出JSON，不要解释。"""


def _get_news_ai_config(db: Session) -> List[Dict]:
    """从系统配置获取新闻AI的API Key列表（支持多API轮询）

    优先使用专用新闻AI多API配置（news_ai_configs），如果没有则回退到通用AI配置。
    按 priority 升序排列（数字越小优先级越高），只返回 enabled=True 的配置。
    """
    import json
    row = db.query(SystemConfig).filter(SystemConfig.config_key == "news_ai_configs").first()
    if row and row.config_value:
        try:
            items = json.loads(row.config_value)
            # 过滤启用的，按优先级排序
            enabled_items = [item for item in items if item.get("enabled", True)]
            enabled_items.sort(key=lambda x: x.get("priority", 99))
            keys = []
            for item in enabled_items:
                if item.get("api_key_encrypted"):
                    try:
                        decrypted = decrypt_api_key(item["api_key_encrypted"])
                        keys.append({
                            "api_key": decrypted,
                            "endpoint": item.get("api_endpoint", ""),
                            "model": item.get("model_name", "gpt-4o-mini"),
                            "provider": item.get("provider", "custom"),
                            "name": item.get("name", ""),
                        })
                    except:
                        pass
            if keys:
                return keys
        except Exception as e:
            logger.warning(f"[NewsAI] 解析多API配置失败: {e}")

    # 回退到通用AI配置（AIConfig 单例表）
    try:
        from backend.models.ai_config import AIConfig
        cfg = db.query(AIConfig).filter(AIConfig.id == AIConfig.SINGLETON_ID).first()
        if cfg and cfg.api_key_encrypted:
            decrypted = decrypt_api_key(cfg.api_key_encrypted)
            if decrypted:
                return [{
                    "api_key": decrypted,
                    "endpoint": cfg.api_endpoint or "",
                    "model": cfg.model_name or "gpt-4o-mini",
                    "provider": cfg.provider_name or "custom",
                    "name": "通用AI配置",
                }]
    except Exception as e:
        logger.debug(f"[NewsAI] 回退通用AI配置失败: {e}")

    return []


def _call_ai_api(api_config: Dict, prompt: str) -> Optional[Dict]:
    """调用单个AI API分析新闻"""
    import requests
    try:
        endpoint = api_config["endpoint"].rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_config['api_key']}",
        }
        payload = {
            "model": api_config["model"],
            "messages": [
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 500,
        }
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=20)
        if resp.status_code != 200:
            logger.debug(f"[NewsAI] API返回 {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        # 提取JSON
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()
        return json.loads(content)
    except Exception as e:
        logger.debug(f"[NewsAI] API调用失败: {e}")
        return None


def analyze_with_ai(db: Session, article: NewsArticle) -> Optional[Dict]:
    """用AI分析单条新闻（多API轮询）"""
    if not _is_important_news(article):
        return None

    api_configs = _get_news_ai_config(db)
    if not api_configs:
        logger.debug("[NewsAI] 未配置AI API，跳过深度分析")
        return None

    prompt = _build_analysis_prompt(article)
    for cfg in api_configs:
        result = _call_ai_api(cfg, prompt)
        if result and "sentiment" in result:
            return result

    logger.warning(f"[NewsAI] 所有API都失败: {article.title[:40]}")
    return None


def batch_analyze_with_ai(db: Session, hours: int = 6, limit: int = 20) -> Dict:
    """批量分析近期重要新闻（关键词预筛选 + 去重已分析新闻）"""
    cutoff = datetime.now() - timedelta(hours=hours)

    # 查询近期新闻，排除已经AI分析过的（analyzed_at有值且含AI关键词的跳过）
    all_articles = db.query(NewsArticle).filter(
        NewsArticle.published_at >= cutoff,
    ).order_by(NewsArticle.published_at.desc()).limit(limit * 3).all()

    # 关键词预筛选 + 去重已分析
    to_analyze = []
    skipped_already_analyzed = 0
    skipped_not_important = 0
    for article in all_articles:
        # 去重：已AI分析过的跳过（sentiment_keywords 含 AI 标记或 is_hot=True 且 analyzed_at 在1小时内）
        if article.is_hot and article.analyzed_at:
            age = (datetime.now() - article.analyzed_at).total_seconds()
            if age < 3600:  # 1小时内分析过的跳过
                skipped_already_analyzed += 1
                continue

        # 关键词预筛选
        filter_result = pre_filter_news(article.title, article.summary or "")
        if filter_result["need_ai"]:
            # 更新预筛选结果到文章（非AI的基础分析）
            if filter_result["symbols"] and not article.related_symbols:
                article.related_symbols = filter_result["symbols"]
            if filter_result["impact_hint"] > article.impact_level:
                article.impact_level = filter_result["impact_hint"]
            to_analyze.append(article)
        else:
            skipped_not_important += 1

        if len(to_analyze) >= limit:
            break

    analyzed = 0
    failed = 0
    for article in to_analyze:
        result = analyze_with_ai(db, article)
        if result:
            article.sentiment_keywords = result.get("key_factors", [])
            if result.get("sentiment_score") is not None:
                article.sentiment_score = float(result["sentiment_score"])
                article.sentiment = 1 if result["sentiment_score"] >= 0.15 else (-1 if result["sentiment_score"] <= -0.15 else 0)
            if result.get("impact_level"):
                article.impact_level = max(article.impact_level, int(result["impact_level"]))
            if result.get("affected_symbols"):
                existing = set(article.related_symbols or [])
                for s in result["affected_symbols"]:
                    existing.add(s)
                article.related_symbols = list(existing)
            article.is_hot = True
            article.analyzed_at = datetime.now()
            analyzed += 1
        else:
            failed += 1

    if analyzed > 0:
        db.commit()

    return {
        "total": len(to_analyze),
        "analyzed": analyzed,
        "failed": failed,
        "skipped_already_analyzed": skipped_already_analyzed,
        "skipped_not_important": skipped_not_important,
        "total_scanned": len(all_articles),
    }
