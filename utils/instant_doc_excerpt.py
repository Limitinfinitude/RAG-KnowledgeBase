"""即时文档问答：轻量摘录检索（字符匹配打分），与向量库 RAG 完全独立。"""
from __future__ import annotations

import hashlib
import re
from typing import List, Tuple


def _chunk_text(text: str, target: int = 720, stride: int = 360) -> List[str]:
    """按段落优先切分，过长段落再滑窗。"""
    parts = re.split(r"\n\s*\n+", text)
    chunks: List[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) > target * 2:
            for i in range(0, len(p), stride):
                seg = p[i : i + target]
                if seg.strip():
                    chunks.append(seg)
            continue
        if len(buf) + len(p) + 2 <= target:
            buf = (buf + "\n\n" + p).strip() if buf else p
        else:
            if buf:
                chunks.append(buf)
            buf = p
    if buf:
        chunks.append(buf)
    if not chunks:
        return [text[:target]] if text.strip() else []
    return chunks


def _query_keys(query: str) -> List[str]:
    q = query.strip()
    if not q:
        return []
    keys: List[str] = []
    # 2-gram（含中英文）
    for i in range(len(q) - 1):
        keys.append(q[i : i + 2])
    # 补充单字（去重后参与弱匹配）
    seen = set(keys)
    for c in q:
        if c.strip() and c not in seen:
            keys.append(c)
            seen.add(c)
    return keys


def score_chunk(chunk: str, keys: List[str]) -> int:
    if not keys:
        return 0
    score = 0
    for k in keys:
        if len(k) >= 2:
            score += chunk.count(k) * 3
        else:
            score += chunk.count(k)
    return score


def select_excerpts(
    document_text: str,
    query: str,
    max_chars: int = 16_000,
    max_chunks: int = 14,
) -> Tuple[str, List[str]]:
    """
    从全文选出与 query 最相关的若干片段拼接，控制总长度。
    若全文不超过 max_chars，直接返回全文与单块列表。
    """
    doc = document_text.strip()
    if not doc:
        return "", []
    if len(doc) <= max_chars:
        return doc, [doc]

    keys = _query_keys(query)
    chunks = _chunk_text(doc)
    scored: List[Tuple[int, int, str]] = []
    for i, ch in enumerate(chunks):
        scored.append((score_chunk(ch, keys), i, ch))
    scored.sort(key=lambda x: (-x[0], x[1]))

    picked: List[str] = []
    total = 0
    used_idx = set()
    for sc, idx, ch in scored:
        if sc <= 0 and len(picked) >= 3:
            break
        if idx in used_idx:
            continue
        if total + len(ch) + 2 > max_chars and picked:
            continue
        used_idx.add(idx)
        picked.append(ch)
        total += len(ch) + 2
        if len(picked) >= max_chunks:
            break

    # 若 query 极短或未命中，退回「开头 + 均匀抽样」避免空上下文
    if not picked:
        head = doc[: max_chars // 2]
        tail = doc[-(max_chars // 4) :] if len(doc) > max_chars // 2 else ""
        merged = (head + "\n\n…\n\n" + tail).strip()
        return merged[:max_chars], [merged[:max_chars]]

    # 按在原文中出现顺序重排，便于模型阅读
    merged_parts = sorted(
        picked,
        key=lambda t: document_text.find(t) if t in document_text else 10**9,
    )
    out = "\n\n---\n\n".join(merged_parts)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out, merged_parts


def select_excerpts_multi(
    document_text: str,
    queries: List[str],
    max_chars: int = 16_000,
    max_chunks_per_query: int = 8,
) -> Tuple[str, List[str]]:
    """
    多子问分别选摘录，按内容去重后合并，控制总长。
    与 RAG 多子查询思路一致，避免一句多问时只命中第一个意图。
    """
    doc = document_text.strip()
    qs = [q.strip() for q in queries if q.strip()][:5]
    if not doc:
        return "", []
    if len(qs) <= 1:
        return select_excerpts(doc, qs[0] if qs else "", max_chars=max_chars)

    per = max(2200, min(max_chars // len(qs) + 400, max_chars))
    seen_hash: set[str] = set()
    merged_parts: List[str] = []
    for q in qs:
        _ex, parts = select_excerpts(
            doc,
            q,
            max_chars=min(per, max_chars),
            max_chunks=max_chunks_per_query,
        )
        for p in parts:
            h = hashlib.md5(p.encode("utf-8", errors="ignore")).hexdigest()[:20]
            if h in seen_hash:
                continue
            seen_hash.add(h)
            merged_parts.append(p)

    merged_parts.sort(key=lambda t: doc.find(t) if t in doc else 10**9)
    out = "\n\n---\n\n".join(merged_parts)
    if len(out) > max_chars:
        out = out[:max_chars]
    return out, merged_parts
