#!/usr/bin/env python3
"""
Pioneer — The Sanctuary Orchestrator
====================================
Connects collector → digester → ChromaDB → Agent.
Persistent memory for local AI running against local disk.

Usage:
  python pioneer.py save "The XX is my AI Sanctuary"
  python pioneer.py search "Sanctuary"
  python pioneer.py ingest ./documents/
  python pioneer.py chat "How do I make a backup?"
  python pioneer.py pipeline https://target.com    # Full cycle

Full pipeline:
  URL → collector (MD) → digester (chunks + links) → ChromaDB (embedding) → Agent
"""

import chromadb
import ollama
import sys
import os
import time
import json
import hashlib
import argparse
import subprocess
from pathlib import Path

# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════

DEFAULT_MODEL = os.environ.get("PIONEER_MODEL", "your-model:8b")
DEFAULT_COLLECTION = os.environ.get("PIONEER_COLLECTION", "general_memory")
DB_PATH = os.path.expanduser(os.environ.get("PIONEER_DB", "~/Pioneer_Memory_DB"))

# Ecosystem module paths
COOKIE_JAR = os.environ.get("COOKIE_JAR_PATH", "collector.py")
DIGESTER = os.environ.get("DIGESTER_PATH", "digester.py")
DIGESTER_OUTPUT = os.path.expanduser("~/digester_output")
COOKIE_OUTPUT = os.path.expanduser("~/collector")

os.makedirs(DB_PATH, exist_ok=True)

# ═══════════════════════════════════════════════════════
# CHROMADB
# ═══════════════════════════════════════════════════════

def get_collection(collection_name):
    client = chromadb.PersistentClient(path=DB_PATH)
    return client.get_or_create_collection(name=collection_name)


def save(text, model, collection, category="general"):
    try:
        emb = ollama.embeddings(model=model, prompt=text)
        vector = emb["embedding"]
    except Exception as e:
        print(f"[ERROR] Embedding with {model}: {e}")
        return

    doc_id = f"{model.replace(':','_')}_{int(time.time())}_{hash(text) % 10000}"
    collection.add(
        ids=[doc_id], embeddings=[vector], documents=[text],
        metadatas=[{"source": "manual", "category": category, "model": model}]
    )
    print(f"[OK] Saved to {collection.name}: {text[:60]}...")


def search(query, model, collection):
    try:
        emb = ollama.embeddings(model=model, prompt=query)
        vector = emb["embedding"]
    except Exception as e:
        print(f"[ERROR] Embedding with {model}: {e}")
        return
    results = collection.query(query_embeddings=[vector], n_results=3)
    if results['documents'][0]:
        print(f"\n>>> {collection.name} remembers ({model}):")
        for i, doc in enumerate(results['documents'][0], 1):
            print(f"{i}. {doc}")
    else:
        print("[INFO] Nothing related found.")


def chat(question, model, collection):
    try:
        emb = ollama.embeddings(model=model, prompt=question)
        vector = emb["embedding"]
    except Exception as e:
        print(f"[ERROR] Embedding with {model}: {e}")
        return
    results = collection.query(query_embeddings=[vector], n_results=3)
    context = "\n\n".join(results['documents'][0]) if results['documents'][0] else ""
    if context:
        print(f"[INFO] {len(results['documents'][0])} memories as context.")
        prompt = f"""You are a personal assistant called Mini-Me. Answer the following question based on the memories you have stored. If the answer is not in the memories, use your general knowledge.

--- Relevant memories ---
{context}

--- Question ---
{question}

--- Answer ---
"""
    else:
        prompt = question
    try:
        response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt}])
        print(f"\n>>> Mini-Me responds:\n{response['message']['content']}")
    except Exception as e:
        print(f"[ERROR] Generating response: {e}")


def ingest_folder(path, model, collection):
    if not os.path.isdir(path):
        print(f"[ERROR] {path} does not exist.")
        return
    files = [f for f in os.listdir(path) if f.endswith(('.txt', '.md'))]
    if not files:
        print("[INFO] No .txt/.md files.")
        return
    print(f"[INFO] {len(files)} files → {collection.name} ({model})")
    for filename in files:
        full_path = os.path.join(path, filename)
        try:
            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read()
            save(content, model, collection, category="document")
        except Exception as e:
            print(f"[WARN] {filename}: {e}")
    print("[OK] Ingestion complete.")


# ═══════════════════════════════════════════════════════
# DIGESTER JSON → CHROMADB (with enriched metadata)
# ═══════════════════════════════════════════════════════

def ingest_digester_json(json_dir, model, collection):
    """Ingest digester-exported JSONs into ChromaDB."""
    if not os.path.isdir(json_dir):
        print(f"[ERROR] {json_dir} is not a directory.")
        return

    json_files = list(Path(json_dir).glob("*.json"))
    if not json_files:
        print("[INFO] No digester JSONs found.")
        return

    total = 0
    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                chunks = json.load(f)
        except Exception as e:
            print(f"[WARN] {jf.name}: {e}")
            continue

        for chunk in chunks:
            meta = chunk.get("meta", {})
            text = chunk["text"]
            chunk_id = chunk["id"]
            links = json.dumps(chunk.get("links", []))

            try:
                emb = ollama.embeddings(model=model, prompt=text)
                vector = emb["embedding"]
            except Exception as e:
                print(f"[WARN] Embedding {chunk_id}: {e}")
                continue

            collection.add(
                ids=[chunk_id],
                embeddings=[vector],
                documents=[text],
                metadatas=[{
                    "source": meta.get("source", "digester"),
                    "category": "digester",
                    "model": model,
                    "title": meta.get("title", ""),
                    "date": meta.get("date", ""),
                    "tags": ",".join(meta.get("tags", [])),
                    "hash": meta.get("hash", ""),
                    "links": links,
                    "chunk_index": meta.get("chunk_index", 0),
                    "chunk_total": meta.get("chunk_total", 0),
                }]
            )
            total += 1

    print(f"[OK] {total} digester chunks ingested into {collection.name}")


# ═══════════════════════════════════════════════════════
# FULL PIPELINE: collector → digester → ChromaDB
# ═══════════════════════════════════════════════════════

def pipeline(target, model=DEFAULT_MODEL, collection_name=DEFAULT_COLLECTION,
             cross_link=False, force=False):
    """Run the full knowledge cycle."""
    print("=" * 50)
    print("PIONEER PIPELINE — Full knowledge cycle")
    print("=" * 50)

    collection = get_collection(collection_name)

    # PHASE 1: Collection (collector)
    print("\n>>> PHASE 1: Collection (collector)")
    if os.path.isfile(COOKIE_JAR):
        cmd = [sys.executable, COOKIE_JAR, target]
        if force:
            cmd.append("--force")
        subprocess.run(cmd)
    else:
        print(f"[WARN] {COOKIE_JAR} not found. Skipping Phase 1.")

    # PHASE 2: Digestion (digester)
    print(f"\n>>> PHASE 2: Digestion (digester)")
    if os.path.isfile(DIGESTER) and os.path.isdir(COOKIE_OUTPUT):
        cmd = [sys.executable, DIGESTER, "--input", COOKIE_OUTPUT, "--output", DIGESTER_OUTPUT]
        if cross_link:
            cmd.append("--cross-link")
        subprocess.run(cmd)
    else:
        print(f"[WARN] {DIGESTER} or {COOKIE_OUTPUT} not found. Skipping Phase 2.")

    # PHASE 3: Embedding + Storage
    print(f"\n>>> PHASE 3: Embedding → ChromaDB ({model})")
    if os.path.isdir(DIGESTER_OUTPUT):
        ingest_digester_json(DIGESTER_OUTPUT, model, collection)
    else:
        # Fallback: direct file ingestion
        ingest_folder(COOKIE_OUTPUT, model, collection)

    print(f"\n[OK] Pipeline complete. Collection: {collection_name}")


# ═══════════════════════════════════════════════════════
# STATISTICS
# ═══════════════════════════════════════════════════════

def stats():
    """Show statistics for all ChromaDB collections."""
    client = chromadb.PersistentClient(path=DB_PATH)
    collections = client.list_collections()
    print(f"\n=== Pioneer — {DB_PATH} ===")
    total_chunks = 0
    for col in collections:
        count = col.count()
        total_chunks += count
        print(f"  {col.name}: {count} chunks")
    print(f"  TOTAL: {total_chunks} chunks")
    disk_usage = sum(
        sum(os.path.getsize(os.path.join(root, f))
            for f in files if not f.startswith("."))
        for root, _, files in os.walk(DB_PATH)
    )
    print(f"  Disk: {disk_usage / (1024**3):.2f} GB")


# ═══════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Pioneer — The Sanctuary Orchestrator",
        epilog="Pipeline: python pioneer.py pipeline https://target.com"
    )
    parser.add_argument("action", nargs="?",
                        choices=["save", "search", "ingest", "chat", "pipeline", "stats", "ingest-digester"],
                        help="Action to perform")
    parser.add_argument("text", nargs="*", help="Text, query, path, or URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help=f"ChromaDB collection (default: {DEFAULT_COLLECTION})")
    parser.add_argument("--cross-link", action="store_true", help="Enable cross-linking in pipeline")
    parser.add_argument("--force", action="store_true", help="Force (ignore locks)")
    args = parser.parse_args()

    if not args.action:
        parser.print_help()
        stats()
        return

    collection = get_collection(args.collection)
    text = " ".join(args.text) if args.text else ""

    if args.action == "save":
        if not text: print("[ERROR] Missing text."); sys.exit(1)
        save(text, args.model, collection)
    elif args.action == "search":
        if not text: print("[ERROR] Missing query."); sys.exit(1)
        search(text, args.model, collection)
    elif args.action == "chat":
        if not text: print("[ERROR] Missing question."); sys.exit(1)
        chat(text, args.model, collection)
    elif args.action == "ingest":
        if not text: print("[ERROR] Missing path."); sys.exit(1)
        ingest_folder(text, args.model, collection)
    elif args.action == "ingest-digester":
        if not text: print("[ERROR] Missing JSON directory."); sys.exit(1)
        ingest_digester_json(text, args.model, collection)
    elif args.action == "pipeline":
        if not text: print("[ERROR] Missing URL or file."); sys.exit(1)
        pipeline(text, args.model, args.collection, args.cross_link, args.force)
    elif args.action == "stats":
        stats()


if __name__ == "__main__":
    main()
