#!/bin/sh
set -eu

git diff --check

for required_file in AGENTS.md docs/devlog.md docs/demo-script.md; do
  if [ ! -s "$required_file" ]; then
    echo "missing or empty required file: $required_file" >&2
    exit 1
  fi
done

if [ -d tests ] && find tests -type f -name 'test_*.py' -print -quit | grep -q .; then
  uv run python -m unittest discover -s tests -p 'test_*.py'
else
  echo "no Python product tests found; permitted before the application scaffold"
fi

if [ -f frontend/package.json ]; then
  pnpm --dir frontend build
fi

tracked_secrets=$(git ls-files | grep -E '(^|/)(\.env|[^/]+\.(pem|key|p12))$' | grep -vE '(^|/)\.env\.example$' || true)
if [ -n "$tracked_secrets" ]; then
  echo "possible secret files are tracked:" >&2
  echo "$tracked_secrets" >&2
  exit 1
fi

echo "repository checks passed"
