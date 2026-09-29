# Pioneer — AI Memory System

**Python · ChromaDB + Ollama · Local-first**

A local-first AI memory system. Collect, digest, and query knowledge — all on your machine.

## What it does

```bash
$ python pioneer.py save "This is an important idea"
[OK] Saved to general_memory

$ python pioneer.py search "idea"
>>> general_memory remembers:
1. This is an important idea

$ python pioneer.py ingest ./documents/
[INFO] 156 files → general_memory
[OK] Ingestion complete.

$ python pioneer.py chat "What were those ideas about?"
[INFO] 3 memories as context.
>>> Mini-Me responds:
Based on your notes...
```

## The 4 core actions

| Action | What it does | Example |
|--------|-------------|---------|
| `save` | Stores text with embedding as a memory | `pioneer.py save "important idea"` |
| `search` | Finds similar memories by meaning | `pioneer.py search "topic"` |
| `ingest` | Loads all .txt/.md files from a folder | `pioneer.py ingest ./books/` |
| `chat` | Full RAG: searches context + generates response | `pioneer.py chat "summarize this"` |

## The ecosystem pipeline

```bash
$ python pioneer.py pipeline https://example.com --cross-link
```

Flow:
1. `collector.py` → scrapes URL → saves clean Markdown
2. `digester.py` → semantic chunks + cross-links → structured JSON
3. `pioneer.py` → embeddings via Ollama → persistent ChromaDB
4. Ready for `search` and `chat`

## Architecture

```
Text → Ollama Embeddings → ChromaDB (local disk)
                                |
User asks → searches context → builds prompt → Mini-Me responds
```

## Features

- **Local-first**: no external APIs. Everything on your machine.
- **Persistent**: ChromaDB on disk. Survives reboots.
- **Multi-collection**: organize memories by topic
- **Model-agnostic**: works with any Ollama model
- **Pipeline mode**: one command from URL to searchable memory
- **Cross-linking**: chunks connected by semantic similarity (TF-IDF)

## Requirements

```bash
pip install chromadb ollama
ollama pull your-model:8b
```

## Why this exists

Built to give local AI real persistent memory — before RAG was a buzzword.
While building it, every vulnerability became obvious. That journey
from builder to defender produced a suite of open-source security tools.

## Versions

| File | OS | DB Path |
|------|-----|---------|
| `pioneer.py` | Linux | `~/Pioneer_Memory_DB` |
| `pioneer_macos.py` | macOS | `~/Library/Application Support/Pioneer/` |
| `pioneer_windows.py` | Windows | `D:\Pioneer_Memory_DB` |
