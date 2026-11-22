#!/usr/bin/env bash
# Download a GGUF model from Hugging Face into models/ and verify its SHA-256.
#
# Usage: scripts/download-model.sh [preset]
#   Presets are defined in the catalog below. Default: qwen2.5-0.5b-q4
#
# Large models are published as split GGUF files (name-00001-of-0000N.gguf).
# Such a preset has one catalog line per part; point MODEL_FILE at the first part
# and llama.cpp loads the remaining parts from the same directory.
set -euo pipefail

# preset | Hugging Face repo | file | sha256
CATALOG="
qwen2.5-0.5b-q4|Qwen/Qwen2.5-0.5B-Instruct-GGUF|qwen2.5-0.5b-instruct-q4_k_m.gguf|74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
qwen2.5-0.5b-q8|Qwen/Qwen2.5-0.5B-Instruct-GGUF|qwen2.5-0.5b-instruct-q8_0.gguf|ca59ca7f13d0e15a8cfa77bd17e65d24f6844b554a7b6c12e07a5f89ff76844e
qwen2.5-7b-q4|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf|dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db
qwen2.5-7b-q4|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf|539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a
qwen2.5-7b-q5|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf|42f6693004793ee6cf1b2b723f0273b10f86a3bb2a949bd9128d4cda5fb866cd
qwen2.5-7b-q5|Qwen/Qwen2.5-7B-Instruct-GGUF|qwen2.5-7b-instruct-q5_k_m-00002-of-00002.gguf|beba9d4f2f5a1fe7d144dcae332e68b52c26705c5310dece2e5d1997e091e134
"

preset="${1:-qwen2.5-0.5b-q4}"
models_dir="$(cd "$(dirname "$0")/.." && pwd)/models"

entries="$(grep "^${preset}|" <<<"$CATALOG" || true)"
if [[ -z "$entries" ]]; then
  echo "Unknown preset: $preset" >&2
  echo "Available presets:" >&2
  grep -v '^$' <<<"$CATALOG" | cut -d'|' -f1 | sort -u | sed 's/^/  /' >&2
  exit 1
fi

mkdir -p "$models_dir"

# Download one file and check it against its SHA-256; skip it if already verified.
fetch() {
  local repo="$1" file="$2" sha256="$3"
  local target="$models_dir/$file"

  if [[ -f "$target" ]] && echo "$sha256  $target" | sha256sum --check --status; then
    echo "Already present and verified: $target"
    return
  fi

  local url="https://huggingface.co/${repo}/resolve/main/${file}"
  echo "Downloading $url"
  # --continue-at - resumes an interrupted download; write to .part first
  # so a half-finished file is never mistaken for a complete one.
  curl --fail --location --progress-bar --continue-at - --output "$target.part" "$url"
  mv "$target.part" "$target"

  if ! echo "$sha256  $target" | sha256sum --check --status; then
    echo "Checksum mismatch for $target, deleting it." >&2
    rm -f "$target"
    exit 1
  fi
  echo "OK: $target"
}

while IFS='|' read -r _ repo file sha256; do
  fetch "$repo" "$file" "$sha256"
done <<<"$entries"
