#!/usr/bin/env bash
# Download a GGUF model from Hugging Face into models/ and verify its SHA-256.
#
# Usage: scripts/download-model.sh [preset]
#   Presets are defined in the catalog below. Default: qwen2.5-0.5b-q4
set -euo pipefail

# preset | Hugging Face repo | file | sha256
CATALOG="
qwen2.5-0.5b-q4|Qwen/Qwen2.5-0.5B-Instruct-GGUF|qwen2.5-0.5b-instruct-q4_k_m.gguf|74a4da8c9fdbcd15bd1f6d01d621410d31c6fc00986f5eb687824e7b93d7a9db
qwen2.5-0.5b-q8|Qwen/Qwen2.5-0.5B-Instruct-GGUF|qwen2.5-0.5b-instruct-q8_0.gguf|ca59ca7f13d0e15a8cfa77bd17e65d24f6844b554a7b6c12e07a5f89ff76844e
"

preset="${1:-qwen2.5-0.5b-q4}"
models_dir="$(cd "$(dirname "$0")/.." && pwd)/models"

entry="$(grep "^${preset}|" <<<"$CATALOG" || true)"
if [[ -z "$entry" ]]; then
  echo "Unknown preset: $preset" >&2
  echo "Available presets:" >&2
  grep -v '^$' <<<"$CATALOG" | cut -d'|' -f1 | sed 's/^/  /' >&2
  exit 1
fi
IFS='|' read -r _ repo file sha256 <<<"$entry"

mkdir -p "$models_dir"
target="$models_dir/$file"

verify() {
  echo "$sha256  $target" | sha256sum --check --status
}

if [[ -f "$target" ]] && verify; then
  echo "Already present and verified: $target"
  exit 0
fi

url="https://huggingface.co/${repo}/resolve/main/${file}"
echo "Downloading $url"
# --continue-at - resumes an interrupted download; write to .part first
# so a half-finished file is never mistaken for a complete one.
curl --fail --location --progress-bar --continue-at - --output "$target.part" "$url"
mv "$target.part" "$target"

if ! verify; then
  echo "Checksum mismatch for $target, deleting it." >&2
  rm -f "$target"
  exit 1
fi
echo "OK: $target"
