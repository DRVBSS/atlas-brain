# Atlas Brain — Configuration Guide

Atlas Brain needs two things to work at full power: an **embedding model** (for semantic search) and an **LLM** (for fact extraction and wiki compilation). Both run locally by default — no API keys required.

---

## LLM Backend Setup

Atlas Brain auto-detects your LLM backend. It checks in this order and uses the first one it finds:

| Priority | Backend | Default Port | How to start |
|----------|---------|-------------|--------------|
| 1 | `ATLAS_LLM_MODEL` env var | — | Manual override (see below) |
| 2 | [msty.ai](https://msty.app) | 10000 | Open the app |
| 3 | [Ollama](https://ollama.com) | 11434 | `ollama serve` |
| 4 | [llama.cpp](https://github.com/ggerganov/llama.cpp) | 8080 | `llama-server -m model.gguf` |
| 5 | Claude API | — | Set `ANTHROPIC_API_KEY` |
| 6 | OpenAI API | — | Set `OPENAI_API_KEY` |

### Option 1: msty.ai (easiest)

[msty.ai](https://msty.app) is a free desktop app that runs models locally with zero configuration.

1. Download and open msty.ai
2. Download a model (e.g., Qwen2.5 or Llama 3)
3. Atlas Brain will auto-detect it on port 10000

**Custom port?** If your msty.ai runs on a different port, set:
```bash
export ATLAS_LLM_MODEL="openai:your-model-name"
export OPENAI_BASE_URL="http://localhost:YOUR_PORT/v1"
```

### Option 2: Ollama (most popular)

1. Install: https://ollama.com
2. Pull a model:
   ```bash
   ollama pull llama3
   ```
3. Start the server:
   ```bash
   ollama serve
   ```
4. Atlas Brain will auto-detect it on port 11434

**Custom port?**
```bash
export OLLAMA_HOST="http://localhost:YOUR_PORT"
```

### Option 3: llama.cpp (most flexible)

Run any GGUF model directly without a wrapper app.

1. Install llama.cpp: https://github.com/ggerganov/llama.cpp
2. Download a GGUF model (e.g., from [HuggingFace](https://huggingface.co/models?search=gguf))
3. Start the server:
   ```bash
   llama-server -m /path/to/model.gguf --port 8080
   ```
4. Atlas Brain will auto-detect it on port 8080

**Custom port?**
```bash
export LLAMA_CPP_PORT=9090
```

Or use the explicit override:
```bash
export ATLAS_LLM_MODEL="llamacpp:my-model"
export OPENAI_BASE_URL="http://localhost:9090/v1"
```

### Option 4: Claude API (best quality)

1. Get an API key from https://console.anthropic.com
2. Set it:
   ```bash
   export ANTHROPIC_API_KEY="sk-ant-..."
   ```
3. Atlas Brain will use `claude-haiku-4-5` by default (fast and cheap)

**Use a different Claude model:**
```bash
export ATLAS_LLM_MODEL="claude:claude-sonnet-4-20250514"
```

### Option 5: OpenAI API

1. Get an API key from https://platform.openai.com
2. Set it:
   ```bash
   export OPENAI_API_KEY="sk-..."
   ```
3. Atlas Brain will use `gpt-4o-mini` by default

**Use a different model:**
```bash
export ATLAS_LLM_MODEL="openai:gpt-4o"
```

### Option 6: Any OpenAI-Compatible Server

Any server that exposes `/v1/chat/completions` works — LM Studio, vLLM, text-generation-webui, etc.

```bash
export ATLAS_LLM_MODEL="openai:your-model-name"
export OPENAI_BASE_URL="http://localhost:YOUR_PORT/v1"
export OPENAI_API_KEY="not-needed"   # some servers require a dummy key
```

---

## Explicit LLM Override

Skip auto-detection entirely by setting `ATLAS_LLM_MODEL`:

```bash
# Format: prefix:model-name
export ATLAS_LLM_MODEL="ollama:llama3"
export ATLAS_LLM_MODEL="claude:claude-haiku-4-5-20251001"
export ATLAS_LLM_MODEL="openai:gpt-4o-mini"
export ATLAS_LLM_MODEL="llamacpp:my-model"
```

Supported prefixes: `ollama:`, `claude:`, `openai:`, `llamacpp:`

---

## LLM Timeout

Fact extraction and wiki compilation make LLM calls that can take a while, especially on slower hardware. The default timeout is 120 seconds.

```bash
export ATLAS_LLM_TIMEOUT_SECONDS=180   # increase for slow models
```

---

## Embedding Model

Atlas Brain uses [nomic-embed-text-v1.5](https://huggingface.co/nomic-ai/nomic-embed-text-v1.5) for semantic search. It downloads automatically on first use (~275MB).

The first ingest will be slow (~2 minutes) while the model loads. Subsequent ingests are fast.

**Skip embeddings for bulk ingestion:**
```bash
atlas ingest /path/to/many/files/ --skip-embed
```

You can generate embeddings later by re-ingesting (dedup will skip the file, but you can rebuild embeddings via the API).

**Set a HuggingFace token** to avoid rate limits during model download:
```bash
export HF_TOKEN="hf_..."
```

---

## Environment Variables Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `ATLAS_LLM_MODEL` | (auto-detect) | LLM backend override. Format: `prefix:model-name` |
| `ATLAS_LLM_TIMEOUT_SECONDS` | `120` | Timeout for LLM API calls |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | Base URL for OpenAI-compatible APIs |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `ANTHROPIC_API_KEY` | — | Claude API key |
| `LLAMA_CPP_PORT` | `8080` | Port for llama.cpp server |
| `HF_TOKEN` | — | HuggingFace token for model downloads |

---

## Verifying Your Setup

After configuration, test that Atlas Brain can reach your LLM:

```bash
atlas init ~/test-brain
cd ~/test-brain

# Create a test file
echo "The capital of France is Paris. It has been since 1792." > test.txt

# Ingest it — fact extraction will exercise the LLM
atlas ingest test.txt

# Check if facts were extracted
atlas facts candidates
```

If fact extraction fails, you'll see `facts` missing from the steps list but `embed` and `fts` will still work — search will function, just without AI-extracted facts.
