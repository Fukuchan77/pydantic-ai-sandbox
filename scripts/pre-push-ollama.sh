#!/usr/bin/env bash
# Live-Ollama integration lane, moved from GitHub Actions to the local
# pre-push gate (CI optimization: GitHub Actions usage-limit control).
#
# WHY LOCAL. Live 8B inference is slow, non-deterministic and environment-bound.
# `integration-ollama.yml` therefore stays `workflow_dispatch`-only on GitHub
# and this script is what actually runs the lane in day-to-day work: it fires
# from the `pre-push` pre-commit stage, so the last thing a developer does
# before publishing a branch is prove the router still talks to a real daemon.
#
# Single source of truth for both entry points:
#   * `.pre-commit-config.yaml` -> pre-push hook `ollama-integration`
#   * `mise.toml`               -> task `test:integration:pre-push`
#
# Behaviour when no daemon is listening: WARN AND SKIP (exit 0). A missing
# local daemon is the normal state on a machine that is only editing docs, and
# a push must not be blocked by it. Set REQUIRE_OLLAMA_PREPUSH=1 to invert that
# into a hard failure (useful in a provider-surface branch, or on a machine
# where the daemon is always expected to be up).
#
# Escape hatches:
#   SKIP_OLLAMA_PREPUSH=1   skip unconditionally, daemon up or not
#   SKIP=ollama-integration pre-commit's own per-hook skip variable
#   git push --no-verify    bypass every pre-push hook
set -euo pipefail

# The OpenAI-compatible base URL carries a `/v1` suffix; the daemon's own
# liveness endpoint sits at the root, so strip it before probing.
base_url="${OLLAMA_BASE_URL:-http://localhost:11434/v1}"
health_url="${base_url%/v1}/api/tags"

if [ "${SKIP_OLLAMA_PREPUSH:-0}" = "1" ]; then
  echo "pre-push: SKIP_OLLAMA_PREPUSH=1 のため live-Ollama 統合テストをスキップします。"
  exit 0
fi

if ! curl -sf --max-time 3 "${health_url}" > /dev/null 2>&1; then
  message="pre-push: Ollama デーモンに接続できません (${health_url})"
  if [ "${REQUIRE_OLLAMA_PREPUSH:-0}" = "1" ]; then
    echo "${message} — REQUIRE_OLLAMA_PREPUSH=1 のため push を中止します。" >&2
    echo "        'ollama serve' で起動してから再実行してください。" >&2
    exit 1
  fi
  echo "${message} — live 統合テストをスキップします。" >&2
  echo "        実行したい場合は 'ollama serve' を起動してから push してください。" >&2
  exit 0
fi

echo "pre-push: Ollama デーモンを検出しました (${health_url}) — live 統合テストを実行します。"

# RUN_INTEGRATION_OLLAMA=1 opts the gated module in (Spec Req 10.3 / T11.1);
# the watsonx e2e in the same directory stays gated by its own
# RUN_INTEGRATION_WATSONX and therefore skips here — metered SaaS is never
# billed from a git hook.
exec env RUN_INTEGRATION_OLLAMA=1 uv run pytest tests/integration
