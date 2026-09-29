# Pioneer — Knowledge Ecosystem

**The complete knowledge cycle: from the web to agent reasoning.**

---

## Architecture

```
                    1. COLLECTION                   2. DIGESTION
                   ┌──────────────┐              ┌──────────────┐
  URLs ───────────→│  collector   │── MD ──────→│   digester   │
  Files ──────────→│  HTML → MD   │              │  chunking    │
                   │  -1 lock     │              │  cross-link  │
                   └──────────────┘              └──────┬───────┘
                                                       │ JSON
                   ┌──────────────┐                     │
                   │   Pioneer    │←────────────────────┘
                   │ Orchestrator │  3. EMBEDDING
                   │ ChromaDB     │
                   │ Ollama       │
                   └──────┬───────┘
                          │                   4. REASONING
                   ┌──────┴───────┐          ┌──────────────┐
                   │    Agent     │─────────→│   Mini-Me    │
                   │    RAG       │ context  │   chat()     │
                   │   search     │─────────→│   respond    │
                   └──────────────┘          └──────────────┘
```

---

## Components

### collector.py — Web Collector
- Converts HTML to clean Markdown
- Organizes by domain/folder
- Lock flag `-1` anti-corruption
- User-Agent rotation
- Rate-limiting delay between requests

```bash
python collector.py https://example.com
python collector.py --input urls.txt
python collector.py https://example.com --force
```

### digester.py — Cognitive Processor
- Chunks by Markdown headers (h1-h4), falls back to paragraphs
- Cross-linking between chunks via TF-IDF + cosine similarity
- Normalization: encoding, whitespace, noise reduction
- Metadata extraction: title, date, tags, hash
- Exports structured JSON ready for ChromaDB

```bash
python digester.py --input ./collector/ --output ./digested/ --cross-link
python digester.py --input document.md --json
```

### pioneer.py — Orchestrator
- 4 core actions: save, search, ingest, chat
- Full pipeline: `pioneer pipeline URL`
- Ingests digester JSON with enriched metadata
- Multi-collection, model-agnostic
- Statistics: `pioneer stats`

```bash
python pioneer.py save "important idea"
python pioneer.py search "topic"
python pioneer.py chat "summarize this"
python pioneer.py pipeline https://example.com --cross-link
python pioneer.py stats
```

---

## Full pipeline

```bash
python pioneer.py pipeline https://example.com --cross-link
```

Flow:
1. `collector.py` → scrapes URL → saves clean Markdown
2. `digester.py` → semantic chunks + cross-links → structured JSON
3. `pioneer.py` → embeddings via Ollama → persistent ChromaDB
4. Ready for `search` and `chat`

---

## Design philosophy

Each layer was designed knowing its vulnerabilities:
- `collector` → what if a site injects malicious JS into the HTML?
- `digester` → what if a chunk contains instructions to the agent?
- `pioneer` → what if the retrieved context is poisoned?

Those questions led to building defense tools alongside the memory system.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Collection | Python stdlib |
| Processing | Python (TF-IDF, regex, hashing) |
| Embeddings | Ollama (local, configurable model) |
| Vector DB | ChromaDB (PersistentClient) |
| Reasoning | Ollama chat API |
| Storage | Local disk |

---

> *"Built the brain. Discovered the attacks. Built the defenses."*
