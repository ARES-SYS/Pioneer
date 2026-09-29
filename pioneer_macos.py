#!/usr/bin/env python3
"""
Pioneer — AI Memory for the Sanctuary (macOS)
January 2026

Persistent memory system with ChromaDB + Ollama.
4 CLI actions: save, search, ingest, chat.
"""

import chromadb
import ollama
import sys
import time
import os
import argparse

DEFAULT_MODEL = "your-model:8b"
DEFAULT_COLLECTION = "general_memory"
DB_PATH = os.path.expanduser("~/Library/Application Support/Pioneer/Pioneer_Memory_DB")

os.makedirs(DB_PATH, exist_ok=True)

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

def main():
    parser = argparse.ArgumentParser(description="Pioneer - AI Memory for the Sanctuary")
    parser.add_argument("action", choices=["save", "search", "ingest", "chat"],
                        help="Action to perform")
    parser.add_argument("text", nargs="+", help="Text, query, or folder path")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model (default: {DEFAULT_MODEL})")
    parser.add_argument("--collection", default=DEFAULT_COLLECTION, help=f"ChromaDB collection (default: {DEFAULT_COLLECTION})")
    args = parser.parse_args()
    text = " ".join(args.text)
    collection = get_collection(args.collection)

    if args.action == "save":
        if not text: print("[ERROR] Missing text."); sys.exit(1)
        save(text, args.model, collection)
    elif args.action == "search":
        if not text: print("[ERROR] Missing query."); sys.exit(1)
        search(text, args.model, collection)
    elif args.action == "ingest":
        if not text: print("[ERROR] Missing path."); sys.exit(1)
        ingest_folder(text, args.model, collection)
    elif args.action == "chat":
        if not text: print("[ERROR] Missing question."); sys.exit(1)
        chat(text, args.model, collection)

if __name__ == "__main__":
    main()
