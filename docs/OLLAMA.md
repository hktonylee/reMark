# Optional enrichment with Ollama

Tagging, summaries, action extraction, and reports can use a local
[Ollama](https://ollama.com) server. Notebook page conversion uses Codex.
Response analysis uses Anthropic when enabled.

## 1. Install Ollama

macOS: `brew install ollama`

Linux: `curl -fsSL https://ollama.com/install.sh | sh`

## 2. Pull the models

```bash
ollama pull llama3.1           # tagging, summaries, actions, reports
ollama pull nomic-embed-text   # semantic search embeddings
```

Different models work too — override them via `llm.ollama.*_model`
in `config.yaml` or from `/settings/llm` in the web dashboard.

## 3. Point reMark at Ollama

`config.yaml`:

```yaml
llm:
  provider: ollama
  ollama:
    base_url: http://localhost:11434
```

## 4. Verify

```bash
remark-bridge sync --once
remark-bridge ask "what is in my last note"
```

For a sync run without Anthropic response analysis, set `response.include_analysis: false`.

## Hardware notes

- A 7B-class text model (llama3.1:8b, mistral) needs ~8 GB RAM.
- Embedding models (`nomic-embed-text`) are tiny — CPU is fine.

## Switching back

Set `llm.provider: anthropic` and `ANTHROPIC_API_KEY` to use Anthropic
for enrichment.
