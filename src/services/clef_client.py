"""Cloudflare Workers AI clef-flash 客户端。

失败时返回 None（fail-open），调用方应放行用户。
永不在日志中输出 API Token。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import httpx
from loguru import logger

from config import Config
from services.clef_prompt import build_questions

CLEF_MODEL = "@cf/cloudflare/clef-flash"
API_PATH = "/client/v4/accounts/{account_id}/ai/run/{model}"
API_BASE = "https://api.cloudflare.com"


@dataclass(frozen=True)
class ClefScore:
    """clef-flash 评分结果。"""

    is_ad: float
    risk_score: float

    def should_auto_kick(self, threshold: Optional[float] = None) -> bool:
        """是否达到自动踢出/封禁阈值。"""
        if threshold is None:
            threshold = Config.CLEF_AUTO_KICK_THRESHOLD
        return self.is_ad >= threshold


def parse_clef_response(payload: dict[str, Any]) -> Optional[ClefScore]:
    """从 Cloudflare API JSON 解析 ClefScore。

    期望结构::

        {
          "success": true,
          "result": {
            "answers": {
              "is_ad": {"type": "noul", "noul": 0.95},
              "risk": {"type": "score", "score": 2.8}
            }
          }
        }
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("success") is False:
        return None

    result = payload.get("result")
    if not isinstance(result, dict):
        return None

    answers = result.get("answers")
    if not isinstance(answers, dict):
        return None

    is_ad_ans = answers.get("is_ad") or {}
    risk_ans = answers.get("risk") or {}

    try:
        is_ad = float(is_ad_ans.get("noul"))
        risk_score = float(risk_ans.get("score"))
    except (TypeError, ValueError):
        return None

    if not (0.0 <= is_ad <= 1.0):
        return None

    return ClefScore(is_ad=is_ad, risk_score=risk_score)


class ClefClient:
    """异步 clef-flash 客户端。"""

    def __init__(
        self,
        account_id: Optional[str] = None,
        api_token: Optional[str] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        self.account_id = account_id if account_id is not None else Config.CLOUDFLARE_ACCOUNT_ID
        self.api_token = api_token if api_token is not None else Config.CLOUDFLARE_AI_TOKEN
        self.timeout = timeout if timeout is not None else Config.CLEF_TIMEOUT
        if enabled is not None:
            self.enabled = enabled
        else:
            self.enabled = Config.CLEF_ENABLED

    def is_configured(self) -> bool:
        """是否已启用且具备必要凭证。"""
        return bool(self.enabled and self.account_id and self.api_token)

    async def score_profile(self, state: str) -> Optional[ClefScore]:
        """对给定 state 文本评分；禁用或出错时返回 None（fail-open）。"""
        if not self.is_configured():
            return None

        if not state or not str(state).strip():
            logger.debug("clef-flash: 空 state，跳过")
            return None

        url = f"{API_BASE}{API_PATH.format(account_id=self.account_id, model=CLEF_MODEL)}"
        body = {
            "model": "clef-flash",
            "state": state,
            "questions": build_questions(),
        }
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException:
            logger.warning("clef-flash 请求超时（fail-open）")
            return None
        except httpx.HTTPError as e:
            # 不记录 headers / token
            logger.warning(f"clef-flash 网络错误（fail-open）: {type(e).__name__}")
            return None
        except Exception as e:
            logger.error(f"clef-flash 未知错误（fail-open）: {type(e).__name__}: {e}")
            return None

        if response.status_code != 200:
            logger.warning(
                f"clef-flash HTTP {response.status_code}（fail-open），body_len={len(response.content)}"
            )
            return None

        try:
            payload = response.json()
        except ValueError:
            logger.warning("clef-flash 响应非 JSON（fail-open）")
            return None

        score = parse_clef_response(payload)
        if score is None:
            logger.warning("clef-flash 响应解析失败（fail-open）")
            return None

        logger.debug(
            f"clef-flash 评分: is_ad={score.is_ad:.4f} risk={score.risk_score:.4f}"
        )
        return score


# 模块级默认客户端，便于 handler 复用
clef_client = ClefClient()
