#!/usr/bin/env bash
# A14: every own Text is PlainText; kit text props that bind live data use Format.plain.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
cd "$ROOT"

fail() { echo "test_qml_plaintext: $*" >&2; exit 1; }

mapfile -t qml_files < <(find . -name '*.qml' -not -path './tests/qml/*' -print | sort)
[[ ${#qml_files[@]} -gt 0 ]] || fail "no QML files"

# Own Text elements must set textFormat: Text.PlainText. Allow the property
# on the same line or the following few lines of the block.
while IFS= read -r hit; do
  file="${hit%%:*}"
  line="${hit#*:}"
  lineno="${line%%:*}"
  start="$lineno"
  end=$((lineno + 12))
  if ! sed -n "${start},${end}p" "$file" | grep -q 'textFormat: *Text.PlainText'; then
    fail "$file:$lineno Text without textFormat: Text.PlainText"
  fi
done < <(grep -nE '^[[:space:]]*Text[[:space:]]*(\{|$)' "${qml_files[@]}" || true)

# Kit text-like props that bind live data must go through Format.plain.
pattern='(snapshot|account|record|caption|help|installHint|message|name|email|home|sharedHealth|provider|setting\(|settings)'
props='(text|tooltipText|label|description|placeholderText):'
while IFS= read -r hit; do
  file="${hit%%:*}"
  rest="${hit#*:}"
  lineno="${rest%%:*}"
  body="${rest#*:}"
  echo "$body" | grep -q 'Format.plain(' && continue
  echo "$body" | grep -qE '^[[:space:]]*(text|tooltipText|label|description|placeholderText):[[:space:]]*["'\'']' && continue
  fail "$file:$lineno kit text prop binds live data without Format.plain: $body"
done < <(grep -nE "$props" "${qml_files[@]}" | grep -E "$pattern" || true)

echo "test_qml_plaintext: ok"
