#!/usr/bin/env bash
#
# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
#
# Detects pytest tests that were newly added by a pull request under
# py/tests/ and runs only those tests. This is a fast supplementary check;
# it does NOT replace the full suite run by python-tests.yml, which still
# runs on every PR and push to master/dev.
#
# Usage: run_new_tests.sh <base_sha> <head_sha>

set -euo pipefail

BASE_SHA="${1:?base sha required}"
HEAD_SHA="${2:?head sha required}"
TEST_GLOB="py/tests/*.py"
MARKER_EXPR="not server"

echo "Comparing ${BASE_SHA} -> ${HEAD_SHA} for changes under ${TEST_GLOB}"

mapfile -t CHANGED_ENTRIES < <(
  git diff --no-renames --name-status --diff-filter=ACM \
    "${BASE_SHA}" "${HEAD_SHA}" -- "${TEST_GLOB}" || true
)

if [[ ${#CHANGED_ENTRIES[@]} -eq 0 ]]; then
  echo "No added/modified files under ${TEST_GLOB}. Nothing to do."
  exit 0
fi

NEW_FILES=()
MODIFIED_FILES=()

for entry in "${CHANGED_ENTRIES[@]}"; do
  status="${entry%%$'\t'*}"
  path="${entry#*$'\t'}"
  if [[ "${status}" == "A" ]]; then
    NEW_FILES+=("${path}")
  else
    MODIFIED_FILES+=("${path}")
  fi
done

EXIT_CODE=0
RAN_ANYTHING=0
{
  echo "### New-tests fast-check"
  echo
} >>"${GITHUB_STEP_SUMMARY:-/dev/null}"

run_pytest() {
  local desc="$1"
  shift
  echo "---- ${desc} ----"
  set +e
  pytest -m "${MARKER_EXPR}" "$@"
  local rc=$?
  set -e
  if [[ ${rc} -eq 5 ]]; then
    echo "::warning::No tests collected for: ${desc} (treating as skipped, not a failure)"
  elif [[ ${rc} -ne 0 ]]; then
    EXIT_CODE=1
  fi
  echo "- ${desc}: exit code ${rc}" >>"${GITHUB_STEP_SUMMARY:-/dev/null}"
}

if [[ ${#NEW_FILES[@]} -gt 0 ]]; then
  RAN_ANYTHING=1
  run_pytest "new file(s): ${NEW_FILES[*]}" "${NEW_FILES[@]}"
fi

for path in "${MODIFIED_FILES[@]}"; do
  [[ -f "${path}" ]] || continue
  funcs=$(
    git diff --no-renames --unified=0 "${BASE_SHA}" "${HEAD_SHA}" -- "${path}" \
      | grep -E '^\+[[:space:]]*def[[:space:]]+test_' \
      | sed -E 's/^\+[[:space:]]*def[[:space:]]+(test_[A-Za-z0-9_]*)\(.*/\1/' \
      | sort -u
  ) || true
  if [[ -n "${funcs}" ]]; then
    RAN_ANYTHING=1
    mapfile -t func_names <<<"${funcs}"
    pattern=$(printf '%s or ' "${func_names[@]}")
    pattern="${pattern% or }"
    run_pytest "newly added test(s) in ${path}: ${funcs//$'\n'/, }" \
      "${path}" -k "${pattern}"
  fi
done

if [[ ${RAN_ANYTHING} -eq 0 ]]; then
  echo "py/tests/ changed, but no newly added test file or test function was detected."
  echo "(This is expected for PRs that only edit existing test bodies, fixtures, or comments.)"
fi

exit "${EXIT_CODE}"
