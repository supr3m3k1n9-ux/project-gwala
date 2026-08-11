#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ORIGIN_REGEX="${GWALA_EXPECTED_ORIGIN_REGEX:-github.com[:/]supr3m3k1n9-ux/project-gwala(\.git)?$}"
VPS_DEPLOY_COMMAND="sudo /srv/projects/gwala/deploy_latest.sh"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

info() {
  printf '%s\n' "$*"
}

python_bin() {
  if [[ -n "${GWALA_PYTHON_BIN:-}" ]]; then
    printf '%s\n' "$GWALA_PYTHON_BIN"
  elif [[ -x ".venv-webull/bin/python" ]]; then
    printf '%s\n' ".venv-webull/bin/python"
  elif [[ -x ".venv/bin/python" ]]; then
    printf '%s\n' ".venv/bin/python"
  else
    printf '%s\n' "python3"
  fi
}

assert_commit_message() {
  local message="${1:-}"
  [[ -n "$message" ]] || fail 'Usage: ./release_gwala.sh "Commit message"'
}

assert_project_repo() {
  local root
  root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "Not inside a Git repository."
  [[ "$(pwd -P)" == "$(cd "$root" && pwd -P)" ]] || fail "Run this script from the Project Gwala repository root: $root"
  [[ -f "AGENTS.md" && -f "run_continuous_assurance.py" && -d "deploy/linux" ]] || fail "This does not look like the Project Gwala repository."
}

assert_main_branch() {
  local branch
  branch="$(git branch --show-current)"
  [[ "$branch" == "main" ]] || fail "Release must run from main. Current branch: ${branch:-detached}"
}

assert_expected_origin() {
  local origin
  origin="$(git remote get-url origin 2>/dev/null)" || fail "Missing Git remote: origin"
  [[ "$origin" =~ $EXPECTED_ORIGIN_REGEX ]] || fail "origin does not point to expected project-gwala repository. Current origin: $origin"
}

protected_path() {
  local path="$1"
  case "$path" in
    data/options_chains/templates|data/options_chains/templates/*) return 1 ;;
    .env|.webull_tokens|.webull_tokens/*|webull_data_sdk.log) return 0 ;;
    config/gwala.env|config/webull_tokens|config/webull_tokens/*) return 0 ;;
    logs|logs/*|backups|backups/*) return 0 ;;
    data/*.csv|data/*.json|data/*.log|data/*.db|data/*.sqlite|data/*.sqlite3|data/*.parquet) return 0 ;;
    data/incidents|data/incidents/*) return 0 ;;
    data/options_chains/*.csv|data/options_chains/active|data/options_chains/active/*) return 0 ;;
    data/options_chains/archive|data/options_chains/archive/*) return 0 ;;
  esac
  return 1
}

placeholder_secret_line() {
  local line="$1"
  [[ "$line" =~ your_|paste_|example|placeholder|dummy|test-|test_|secret-app-password|super-secret|token-value|redacted ]]
}

secret_assignment_line() {
  local line="$1"
  [[ "$line" =~ (WEBULL_APP_SECRET|WEBULL_APP_KEY|WEBULL_ACCESS_TOKEN|WEBULL_REFRESH_TOKEN|POLYGON_API_KEY|GWALA_SMTP_PASSWORD|SMTP_PASSWORD|EMAIL_PASSWORD|GMAIL_APP_PASSWORD|API_SECRET|ACCESS_TOKEN|REFRESH_TOKEN)[[:space:]]*[:=][[:space:]]*[\"\'\ ]*[^\"\'\ ]{8,} ]]
}

audit_file_content() {
  local file="$1"
  local line_number=0
  [[ -f "$file" ]] || return 0
  grep -Iq . "$file" || return 0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line_number=$((line_number + 1))
    if secret_assignment_line "$line" && ! placeholder_secret_line "$line"; then
      printf 'Potential secret assignment: %s:%s (value redacted)\n' "$file" "$line_number" >&2
      return 1
    fi
    if [[ "$line" == *"-----BEGIN "*PRIVATE*KEY*"-----"* ]]; then
      printf 'Potential private key material: %s:%s (value redacted)\n' "$file" "$line_number" >&2
      return 1
    fi
  done < "$file"
}

audit_candidate_files() {
  local label="$1"
  local failed=0
  local file
  while IFS= read -r -d '' file; do
    if protected_path "$file"; then
      printf 'Protected path present in %s release set: %s\n' "$label" "$file" >&2
      failed=1
      continue
    fi
    if ! audit_file_content "$file"; then
      failed=1
    fi
  done < <(git ls-files --cached --others --exclude-standard -z)
  [[ "$failed" -eq 0 ]] || fail "Secret/protected-path audit failed before staging."
}

audit_staged_files() {
  local failed=0
  local file
  while IFS= read -r -d '' file; do
    if protected_path "$file"; then
      printf 'Protected path staged for release: %s\n' "$file" >&2
      failed=1
      continue
    fi
    if ! audit_file_content "$file"; then
      failed=1
    fi
  done < <(git diff --cached --name-only --diff-filter=ACMR -z)
  [[ "$failed" -eq 0 ]] || fail "Secret/protected-path audit failed after staging."
}

run_syntax_validation() {
  local python
  python="$(python_bin)"
  "$python" - <<'PY'
from pathlib import Path
import subprocess
import sys

completed = subprocess.run(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.py"],
    check=True,
    capture_output=True,
    text=True,
)
failed = []
for raw_path in completed.stdout.splitlines():
    path = Path(raw_path)
    try:
        source = path.read_text(encoding="utf-8")
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        failed.append(f"{path}:{exc.lineno}: syntax error: {exc.msg}")
    except OSError as exc:
        failed.append(f"{path}: unable to read: {exc}")
if failed:
    print("\n".join(failed), file=sys.stderr)
    sys.exit(1)
print("Syntax validation passed.")
PY
}

run_focused_safety_tests() {
  local python
  python="$(python_bin)"
  "$python" -m unittest tests.test_continuous_assurance tests.test_workflow_safety -v
}

stage_release_changes() {
  git add -A -- . \
    ':(exclude).env' \
    ':(exclude).webull_tokens/**' \
    ':(exclude)webull_data_sdk.log' \
    ':(exclude)config/gwala.env' \
    ':(exclude)config/webull_tokens/**' \
    ':(exclude)logs/**' \
    ':(exclude)backups/**' \
    ':(glob,exclude)data/*.csv' \
    ':(glob,exclude)data/*.json' \
    ':(glob,exclude)data/*.log' \
    ':(glob,exclude)data/*.db' \
    ':(glob,exclude)data/*.sqlite' \
    ':(glob,exclude)data/*.sqlite3' \
    ':(glob,exclude)data/*.parquet' \
    ':(exclude)data/incidents/**' \
    ':(glob,exclude)data/options_chains/*.csv' \
    ':(exclude)data/options_chains/active/**' \
    ':(exclude)data/options_chains/archive/**'
}

show_staged_summary() {
  info "Staged change summary:"
  git diff --cached --stat --summary
  git status --short
}

main() {
  local message="${1:-}"
  assert_commit_message "$message"
  assert_project_repo
  assert_main_branch
  assert_expected_origin

  info "Running pre-stage secret/protected-path audit..."
  audit_candidate_files "non-ignored"

  info "Running syntax validation..."
  run_syntax_validation

  info "Running focused safety tests..."
  run_focused_safety_tests

  info "Staging release changes..."
  stage_release_changes

  if git diff --cached --quiet; then
    fail "No staged changes to release."
  fi

  info "Running staged secret/protected-path audit..."
  audit_staged_files

  show_staged_summary

  info "Committing release..."
  git commit -m "$message"

  local commit_sha
  commit_sha="$(git rev-parse HEAD)"

  info "Pushing main to origin..."
  git push origin main

  info ""
  info "Release complete."
  info "Commit SHA: $commit_sha"
  info "Commit message: $message"
  info "Push result: success"
  info "Next VPS command:"
  info "  $VPS_DEPLOY_COMMAND"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
