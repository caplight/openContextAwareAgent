"""评估闭环的 FastAPI 路由（引导 UX 后端）。

MVP 最小闭环（`docs/mvp-design.md` §8）：
1. 上传文档 → 切分 + 索引
2. 生成种子问题
3. 跑评估（当前 top_k）
4. 跑多组 top_k → 建议
5. 确认采纳 → 写回 top_k

约束：单助手（固定 `assistant_id="default"`）、只调 `top_k` 一个参数、不做 golden case 回归。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel

from enterprise_kb import assistant as assistant_mod
from enterprise_kb import embed, ingest
from enterprise_kb.assistant import get_resolved_config
from enterprise_kb.config import get_settings
from enterprise_kb.evaluate import run_evaluation
from enterprise_kb.logging import get_logger
from enterprise_kb.orchestrator import apply_suggestion, suggest_top_k_workflow
from enterprise_kb.rating import Rating
from enterprise_kb.seed_questions import SeedQuestion, generate_seed_questions
from enterprise_kb.suggest import Suggestion

logger = get_logger(__name__)

router = APIRouter(prefix="/api/eval", tags=["eval"])

DEFAULT_ASSISTANT_ID = "default"

# 复用 ingest 支持的文档类型（MVP 聚焦 PDF，但不硬编码）
_SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".rst"}


# ---------- 请求模型 ----------

class SeedQuestionsRequest(BaseModel):
    n: int = 25


class EvaluateRequest(BaseModel):
    questions: list[SeedQuestion]


class SuggestRequest(BaseModel):
    questions: list[SeedQuestion]
    ratings: list[Rating] = []


class ApplyRequest(BaseModel):
    """前端把 suggest 返回的 Suggestion 原样传回，确认采纳。"""

    param: str
    current: int
    recommended: int
    reason: str
    confidence: float
    category: str = "weak"


# ---------- 辅助 ----------

def _ensure_default_assistant() -> None:
    """确保默认助手存在（固定 id，避免 upsert 外键失败）。"""
    with assistant_mod._connect() as conn:  # noqa: SLF001
        exists = conn.execute(
            "SELECT 1 FROM assistants WHERE id = ?", (DEFAULT_ASSISTANT_ID,)
        ).fetchone()
        if exists is None:
            conn.execute(
                "INSERT INTO assistants (id, name, template, created_at) VALUES (?, ?, ?, ?)",
                (DEFAULT_ASSISTANT_ID, "默认助手", None, assistant_mod._now()),  # noqa: SLF001
            )


# ---------- 1. 上传文档 ----------

@router.post("/upload")
async def upload_document(file: UploadFile):
    """保存上传的文档到 docs_dir，切分 + 索引，返回 chunk 数。"""
    name = file.filename or ""
    suffix = ("." + name.rsplit(".", 1)[-1]).lower() if "." in name else ""
    if suffix not in _SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"不支持的文档类型: {suffix or '(无扩展名)'}")

    docs_dir = get_settings().docs_dir
    docs_dir.mkdir(parents=True, exist_ok=True)
    dest = docs_dir / name
    dest.write_bytes(await file.read())

    chunks = ingest.load_and_split(docs_dir)
    chunk_count = embed.index_chunks(chunks)
    logger.info("已上传 %s，索引 %d 个 chunk", name, chunk_count)
    return {"filename": name, "chunk_count": chunk_count}


# ---------- 2. 生成种子问题 ----------

@router.post("/seed-questions")
def seed_questions(req: SeedQuestionsRequest):
    """从已上传文档生成种子问题（用户可编辑/删除）。"""
    chunks = ingest.load_and_split()
    if not chunks:
        raise HTTPException(status_code=400, detail="尚无文档，请先上传")
    questions = generate_seed_questions(chunks, n=req.n)
    return {"questions": [q.model_dump() for q in questions]}


# ---------- 3. 跑评估 ----------

@router.post("/evaluate")
def evaluate(req: EvaluateRequest):
    """对种子问题跑一轮评估（当前 top_k），返回逐条 faithfulness / context_precision。"""
    if not req.questions:
        raise HTTPException(status_code=400, detail="种子问题为空")
    _ensure_default_assistant()
    config = get_resolved_config(DEFAULT_ASSISTANT_ID)
    run = run_evaluation(req.questions, config=config)
    return {"results": [r.model_dump() for r in run.results]}


# ---------- 4. 建议 ----------

@router.post("/suggest")
def suggest(req: SuggestRequest):
    """跑多组 top_k → 输出可解释建议（或 None，表示无需调整）。"""
    if not req.questions:
        raise HTTPException(status_code=400, detail="种子问题为空")
    _ensure_default_assistant()
    suggestion = suggest_top_k_workflow(
        DEFAULT_ASSISTANT_ID,
        req.questions,
        ratings=req.ratings or None,
    )
    return {"suggestion": suggestion.model_dump() if suggestion else None}


# ---------- 5. 确认采纳 ----------

@router.post("/apply")
def apply(req: ApplyRequest):
    """用户确认采纳 → 写回 top_k，返回更新后的配置。"""
    _ensure_default_assistant()
    suggestion = Suggestion(
        param=req.param,
        current=req.current,
        recommended=req.recommended,
        reason=req.reason,
        confidence=req.confidence,
        category=req.category,
    )
    resolved = apply_suggestion(DEFAULT_ASSISTANT_ID, suggestion)
    return {"top_k": resolved.top_k, "config": resolved.model_dump()}
