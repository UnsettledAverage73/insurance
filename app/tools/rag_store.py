"""Embedded LanceDB vector store for P&C policy wordings and AMS support runbooks."""

from __future__ import annotations

import hashlib
import math
import os
import re
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa

EMBED_DIM = 256
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = PROJECT_ROOT / "sample_data"

DOMAIN_SYNONYMS: dict[str, list[str]] = {
    "auto_glass": ["windshield", "glass", "breakage", "end-glass-01", "ca-2026"],
    "windshield": ["auto_glass", "glass", "end-glass-01"],
    "flood": ["surface water", "inundation", "storm surge", "ex-fld-09", "excluded"],
    "theft": ["stolen", "larceny", "vandalism", "end-comp-02", "comprehensive"],
    "fire": ["lightning", "smoke", "end-fire-01", "bf-2026"],
    "err_policy_sync_mismatch": ["sop-ams-001", "lapsed", "active", "cc_policy_cache", "sync"],
    "err_missing_endorsement": ["sop-ams-002", "truncated", "endorsement_code", "webhook"],
    "err_malformed_payload": ["sop-ams-003", "schema", "validation", "malformed"],
    "err_payout_webhook_504": ["sop-ams-004", "504", "timeout", "disbursement"],
    "err_rule_conflict": ["sop-ams-005", "conflict", "contradictory"],
}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9_-]+", text.lower())
    expanded: list[str] = list(tokens)
    for tok in tokens:
        if tok in DOMAIN_SYNONYMS:
            expanded.extend(DOMAIN_SYNONYMS[tok])
    return expanded


def _embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Compute a deterministic L2-normalized dense vector without external model downloads."""
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        vec[0] = 1.0
        return vec

    features = list(tokens)
    for idx in range(len(tokens) - 1):
        features.append(f"{tokens[idx]}_{tokens[idx + 1]}")

    for feat in features:
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if (digest[4] & 1) == 0 else -1.0
        weight = 2.0 if ("-" in feat or "_" in feat) else 1.0
        vec[bucket] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _parse_markdown_sections(file_path: Path, doc_type: str) -> list[dict[str, Any]]:
    """Split a markdown knowledge document by level-2 headings (## )."""
    raw = file_path.read_text(encoding="utf-8")
    blocks = re.split(r"(?m)^## ", raw)
    chunks: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        stripped = block.strip()
        if not stripped or stripped.startswith("# "):
            continue
        lines = stripped.splitlines()
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        code_match = re.search(r"((?:END|EX|COND)-[A-Z0-9-]+|SOP-AMS-\d{3}|ERR_[A-Z0-9_]+)", stripped)
        section_code = code_match.group(1) if code_match else f"SEC-{idx}"
        full_text = f"{title}\n{body}"
        chunks.append(
            {
                "doc_id": f"{doc_type}-{idx:02d}",
                "doc_type": doc_type,
                "source": file_path.name,
                "section_code": section_code,
                "title": title,
                "content": full_text,
                "vector": _embed_text(full_text),
            }
        )
    return chunks


class InsureOpsRAGStore:
    """Manages LanceDB tables for Policy Wordings and AMS Support Runbooks."""

    def __init__(self, db_dir: str | Path | None = None) -> None:
        resolved_dir = Path(db_dir or os.getenv("LANCEDB_DIR", PROJECT_ROOT / ".lancedb"))
        resolved_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(resolved_dir))
        self._schema = pa.schema(
            [
                pa.field("doc_id", pa.string()),
                pa.field("doc_type", pa.string()),
                pa.field("source", pa.string()),
                pa.field("section_code", pa.string()),
                pa.field("title", pa.string()),
                pa.field("content", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), EMBED_DIM)),
            ]
        )
        self._ensure_indexed()

    def _ensure_indexed(self) -> None:
        policy_chunks = _parse_markdown_sections(SAMPLE_DATA_DIR / "commercial_auto_policy.md", "policy")
        runbook_chunks = _parse_markdown_sections(SAMPLE_DATA_DIR / "ams_support_runbook.md", "runbook")

        self.policy_table = self.db.create_table(
            "policy_wordings",
            data=policy_chunks,
            schema=self._schema,
            mode="overwrite",
        )
        self.runbook_table = self.db.create_table(
            "ams_runbooks",
            data=runbook_chunks,
            schema=self._schema,
            mode="overwrite",
        )

    def _hybrid_rerank(
        self, rows: list[dict[str, Any]], query: str, exact_hints: list[str], top_k: int
    ) -> list[dict[str, Any]]:
        query_terms = set(_tokenize(query))
        hint_terms = {h.lower() for h in exact_hints if h}

        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            content_lower = row["content"].lower()
            code_lower = row["section_code"].lower()
            vec_distance = float(row.get("_distance", 1.0))
            vec_sim = max(0.0, 1.0 - vec_distance / 2.0)

            overlap = sum(1 for t in query_terms if t in content_lower)
            hint_bonus = 0.0
            for hint in hint_terms:
                if hint in code_lower:
                    hint_bonus += 3.0
                elif hint in content_lower:
                    hint_bonus += 1.5

            total_score = vec_sim + 0.15 * overlap + hint_bonus
            clean_row = {
                "doc_id": row["doc_id"],
                "source": row["source"],
                "section_code": row["section_code"],
                "title": row["title"],
                "content": row["content"],
                "score": round(total_score, 4),
            }
            scored.append((total_score, clean_row))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:top_k]]

    def retrieve_policy_clauses(
        self,
        query: str,
        endorsement_code: str = "",
        loss_type: str = "",
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant policy coverage and exclusion clauses from LanceDB."""
        enriched_query = f"{query} {endorsement_code} {loss_type}".strip()
        qvec = _embed_text(enriched_query)
        raw_rows = self.policy_table.search(qvec).limit(6).to_list()
        return self._hybrid_rerank(raw_rows, enriched_query, [endorsement_code, loss_type], top_k)

    def retrieve_runbooks(
        self,
        query: str,
        error_code: str = "",
        top_k: int = 2,
    ) -> list[dict[str, Any]]:
        """Retrieve relevant AMS L2 troubleshooting SOPs from LanceDB."""
        enriched_query = f"{query} {error_code}".strip()
        qvec = _embed_text(enriched_query)
        raw_rows = self.runbook_table.search(qvec).limit(5).to_list()
        return self._hybrid_rerank(raw_rows, enriched_query, [error_code], top_k)


_rag_store: InsureOpsRAGStore | None = None


def get_rag_store() -> InsureOpsRAGStore:
    """Return a singleton LanceDB RAG store instance."""
    global _rag_store
    if _rag_store is None:
        _rag_store = InsureOpsRAGStore()
    return _rag_store
