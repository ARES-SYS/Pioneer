#!/usr/bin/env python3
"""
digester.py — The Cognitive Processor
======================================
Takes raw documents, digests them semantically.
Intelligent chunking, cross-linking, cleaning, normalization.

Usage:
  python digester.py ./docs/
  python digester.py --input document.md
  python digester.py --input ./docs/ --output ./digested/ --cross-link

Pipeline:
  1. Ingest    → detect type, extract text
  2. Clean     → normalize encoding, strip noise
  3. Chunk     → split by headers, paragraphs, or semantically
  4. Link      → cross-link related chunks (TF-IDF)
  5. Metadata  → title, source, date, tags, hash
  6. Export    → structured JSON ready for ChromaDB
"""

import os
import sys
import re
import json
import math
import hashlib
import argparse
import time
from pathlib import Path
from collections import Counter

# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════

DEFAULT_CHUNK_SIZE = int(os.environ.get("DIGESTER_CHUNK_SIZE", "1000"))
DEFAULT_CHUNK_OVERLAP = int(os.environ.get("DIGESTER_CHUNK_OVERLAP", "100"))
DEFAULT_LINK_LIMIT = int(os.environ.get("DIGESTER_LINK_LIMIT", "5"))
LOCK_FLAG = "-1"
os.makedirs(os.path.expanduser("~/digester_output"), exist_ok=True)

# ═══════════════════════════════════════════════════════
# CLEANING AND NORMALIZATION
# ═══════════════════════════════════════════════════════

def normalize_text(text: str) -> str:
    """Clean and normalize text for chunking."""
    text = re.sub(r'[^\x20-\x7E\xA0-\xFF\u00C0-\u024F\u1E00-\u1EFF\n]', '', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'^\s*[-=_#~*]{3,}\s*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'^https?://\S+\s*$', '', text, flags=re.MULTILINE)
    return text.strip()


def extract_metadata(text: str, source: str) -> dict:
    """Extract metadata from text."""
    lines = text.split("\n")[:30]
    title = source
    tags = []
    date = ""

    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    date_pattern = r'(\d{4}[-/]\d{2}[-/]\d{2})'
    match = re.search(date_pattern, text[:500])
    if match:
        date = match.group(1)

    keywords = {"python": "python", "llm": "llm", "agent": "agent",
                 "rag": "rag", "code": "code", "data": "data",
                 "api": "api", "docs": "docs", "research": "research"}
    text_lower = text.lower()
    for kw, tag in keywords.items():
        if kw in text_lower:
            tags.append(tag)

    return {
        "title": title,
        "source": source,
        "date": date,
        "tags": list(set(tags)),
        "hash": hashlib.sha256(text.encode()).hexdigest()[:16],
        "size": len(text),
        "lines": text.count("\n") + 1,
    }


# ═══════════════════════════════════════════════════════
# CHUNKING
# ═══════════════════════════════════════════════════════

def chunk_by_headers(text: str) -> list[str]:
    """Split by Markdown headers (h1-h4)."""
    chunks = re.split(r'\n(?=#{1,4} )', text)
    return [c.strip() for c in chunks if c.strip() and len(c.strip()) > 20]


def chunk_by_paragraphs(text: str, min_size: int = 100) -> list[str]:
    """Split by paragraphs, merging small ones."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) > DEFAULT_CHUNK_SIZE and current:
            chunks.append(current.strip())
            current = p
        else:
            current = (current + "\n\n" + p).strip()
    if current and len(current) > min_size:
        chunks.append(current)
    return chunks


def chunk_semantic(text: str, max_size: int = DEFAULT_CHUNK_SIZE,
                   overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Semantic chunking: respects headers and paragraphs, with overlap."""
    header_chunks = chunk_by_headers(text)
    if len(header_chunks) >= 3:
        base_chunks = header_chunks
    else:
        base_chunks = chunk_by_paragraphs(text)

    final_chunks = []
    for ch in base_chunks:
        if len(ch) <= max_size:
            final_chunks.append(ch)
        else:
            words = ch.split()
            i = 0
            while i < len(words):
                sub = " ".join(words[i:i + max_size // 5])
                if len(sub) > 50:
                    final_chunks.append(sub)
                i += (max_size // 5) - (overlap // 5)
                if i >= len(words):
                    break
    return final_chunks


# ═══════════════════════════════════════════════════════
# CROSS-LINKING (simplified TF-IDF)
# ═══════════════════════════════════════════════════════

def tokenize(text: str) -> list[str]:
    """Tokenize text into terms."""
    return re.findall(r'\b[a-z]{3,}\b', text.lower())


def compute_tfidf(chunks: list[str]) -> list[dict]:
    """Compute TF-IDF for a list of chunks."""
    N = len(chunks)
    tokens_list = [tokenize(c) for c in chunks]
    df = Counter()
    for tokens in tokens_list:
        for term in set(tokens):
            df[term] += 1
    tfidf_list = []
    for tokens in tokens_list:
        tf = Counter(tokens)
        vector = {}
        for term, count in tf.items():
            idf = math.log((N + 1) / (df[term] + 1)) + 1
            vector[term] = count * idf
        tfidf_list.append(vector)
    return tfidf_list


def cosine_similarity(a: dict, b: dict) -> float:
    """Cosine similarity between two TF-IDF vectors."""
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b))
    norm_a = math.sqrt(sum(v ** 2 for v in a.values()))
    norm_b = math.sqrt(sum(v ** 2 for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def cross_link(chunks: list[str], limit: int = DEFAULT_LINK_LIMIT) -> list[dict]:
    """Link related chunks using TF-IDF cosine similarity."""
    if len(chunks) < 2:
        return [{"chunk": c, "links": []} for c in chunks]

    tfidf = compute_tfidf(chunks)
    linked = []
    for i, (chunk, vec) in enumerate(zip(chunks, tfidf)):
        similarities = []
        for j, other_vec in enumerate(tfidf):
            if i == j:
                continue
            sim = cosine_similarity(vec, other_vec)
            if sim > 0.1:
                similarities.append((j, sim))
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_links = similarities[:limit]
        linked.append({
            "chunk": chunk,
            "links": [{"to": j, "score": round(sim, 3)} for j, sim in top_links],
        })
    return linked


# ═══════════════════════════════════════════════════════
# MAIN PIPELINE
# ═══════════════════════════════════════════════════════

def digest_file(filepath: str, cross_link_enabled: bool = False,
                output_dir: str = None) -> list[dict]:
    """Process a file: clean, chunk, cross-link, export."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except Exception as e:
        print(f"  [ERROR] Cannot read {filepath}: {e}")
        return []

    if not raw.strip():
        return []

    print(f"  [READ] {filepath} ({len(raw)} bytes)")

    text = normalize_text(raw)
    meta = extract_metadata(text, filepath)

    chunks = chunk_semantic(text)
    print(f"  [CHUNKS] {len(chunks)} fragments (max={DEFAULT_CHUNK_SIZE}, overlap={DEFAULT_CHUNK_OVERLAP})")

    linked = cross_link(chunks) if cross_link_enabled else [{"chunk": c, "links": []} for c in chunks]
    if cross_link_enabled:
        total_links = sum(len(li["links"]) for li in linked)
        print(f"  [LINKS] {total_links} cross-links")

    results = []
    for i, item in enumerate(linked):
        chunk_id = f"{meta['hash']}_{i:04d}"
        results.append({
            "id": chunk_id,
            "text": item["chunk"],
            "links": item["links"],
            "meta": {**meta, "chunk_index": i, "chunk_total": len(linked)},
        })

    if output_dir:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        out_path = os.path.join(output_dir, f"{basename}_{meta['hash']}.json")
        os.makedirs(output_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"  [EXPORT] {out_path}")

    return results


def digest_directory(dirpath: str, cross_link_enabled: bool = False,
                     output_dir: str = None) -> list[dict]:
    """Recursively process all .md and .txt files in a directory."""
    all_results = []
    extensions = (".md", ".txt", ".rst", ".org")

    lock_file = os.path.join(dirpath, f"_{LOCK_FLAG}")
    if os.path.exists(lock_file):
        print(f"[LOCK] {dirpath} has -1 lock. Skipping.")
        return []

    files = []
    for root, dirs, filenames in os.walk(dirpath):
        if os.path.exists(os.path.join(root, f"_{LOCK_FLAG}")):
            continue
        for fn in filenames:
            if fn.endswith(extensions) and not fn.startswith("."):
                files.append(os.path.join(root, fn))

    print(f"[INFO] {len(files)} files in {dirpath}")
    for filepath in sorted(files):
        results = digest_file(filepath, cross_link_enabled, output_dir)
        all_results.extend(results)

    return all_results


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="digester.py — Cognitive document processor",
        epilog="Example: python digester.py --input ./docs/ --output ./digested/ --cross-link"
    )
    parser.add_argument("--input", required=True, help="File or directory to process")
    parser.add_argument("--output", help="Output directory for digested JSONs")
    parser.add_argument("--cross-link", action="store_true", help="Enable cross-linking between chunks")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f"Max chunk size (default: {DEFAULT_CHUNK_SIZE})")
    parser.add_argument("--overlap", type=int, default=DEFAULT_CHUNK_OVERLAP,
                        help=f"Overlap between chunks (default: {DEFAULT_CHUNK_OVERLAP})")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of text")
    args = parser.parse_args()

    import digester as _self
    _self.DEFAULT_CHUNK_SIZE = args.chunk_size
    _self.DEFAULT_CHUNK_OVERLAP = args.overlap

    start = time.time()

    if os.path.isfile(args.input):
        results = digest_file(args.input, args.cross_link, args.output)
    else:
        results = digest_directory(args.input, args.cross_link, args.output)

    elapsed = time.time() - start

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        total_chars = sum(len(r["text"]) for r in results)
        print(f"\n[OK] {len(results)} chunks in {elapsed:.1f}s ({total_chars} total characters)")

        if args.output:
            print(f"[OK] Exported to: {args.output}")


if __name__ == "__main__":
    main()
