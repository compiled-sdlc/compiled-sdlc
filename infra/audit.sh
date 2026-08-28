#!/usr/bin/env bash
#
# Repository hygiene audit.
#
# Runs the four pre-push checks plus any project-specific assertions.
# Every check must produce no output; the script exits non-zero if any
# check produces output, and prints the offending lines.
#
# Usage:
#   infra/audit.sh              run all checks
#   infra/audit.sh --install-hook   install this script as a pre-push hook

set -uo pipefail

cd "$(dirname "$0")/.." || exit 2

if [ "${1:-}" = "--install-hook" ]; then
    hook=".git/hooks/pre-push"
    printf '#!/usr/bin/env bash\nexec "$(git rev-parse --show-toplevel)"/infra/audit.sh\n' > "$hook"
    chmod +x "$hook"
    echo "installed $hook"
    exit 0
fi

# The forbidden-token patterns below are assembled from string fragments so
# that this script does not itself contain the literal tokens it forbids in
# tracked content (check 2 scans this file too).
tool_names='c''laude|cop''ilot|chat''gpt|anthro''pic|open''ai|ai[- ]assist'
attribution='co-''authored-by|gene''rated (with|by)'
forbidden_paths='\.(docx|pdf|pptx)$|^manuscript/|^docs/|_INSTRUCTIONS|_BRIEF|notes/'

# LICENSE is excluded from check 2 (see below), so it is pinned by content
# instead: with its filled-in copyright line normalised back to the upstream
# placeholder, LICENSE must hash to the canonical Apache-2.0 text. Any other
# edit to the file — including a smuggled tool reference the excluded pathspec
# would otherwise hide — changes the hash and fails check 5.
apache_2_0_sha256='cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30'
copyright_line='   Copyright 2026 Syed Moid'
copyright_placeholder='   Copyright [yyyy] [name of copyright owner]'

# Project-specific assertions (extend as the work stabilises).
# ABSENT: strings that must never appear in tracked content — internal
# labels, stale numbers, draft watermarks.
# PRESENT: strings that must appear — current headline values, the DOI once
# minted.
ABSENT_PATTERNS=()
PRESENT_PATTERNS=()

failures=0

sha256() {
    if command -v shasum > /dev/null 2>&1; then
        shasum -a 256 | cut -d' ' -f1
    else
        sha256sum | cut -d' ' -f1
    fi
}

license_integrity() {
    if [ ! -f LICENSE ]; then
        echo "LICENSE is missing"
        return
    fi
    if ! grep -qxF "${copyright_line}" LICENSE; then
        echo "LICENSE copyright line is not the expected one"
        return
    fi
    local actual
    actual="$(sed "s|^${copyright_line}\$|${copyright_placeholder}|" LICENSE | sha256)"
    if [ "${actual}" != "${apache_2_0_sha256}" ]; then
        echo "LICENSE does not match the canonical Apache-2.0 text"
        echo "expected sha256 ${apache_2_0_sha256}, got ${actual}"
    fi
}

run_check() {
    local name="$1" cmd="$2" out
    out="$(eval "$cmd" 2>/dev/null)"
    if [ -n "$out" ]; then
        printf 'FAIL  %s\n' "$name"
        printf '%s\n' "$out" | sed 's/^/        /'
        failures=$((failures + 1))
    else
        printf 'ok    %s\n' "$name"
    fi
}

run_check "1. no attribution or tool references in commit messages" \
    "git log --format='%B' | grep -inE '${attribution}|${tool_names}'"

# LICENSE is excluded from check 2: the verbatim Apache-2.0 text contains the
# phrase "gene""rated by" in its Derivative Works clause. Check 5 pins the file
# so the exclusion cannot hide a real leak.
run_check "2. no tool references in tracked content" \
    "git grep -ilE '${tool_names}|gene''rated by' -- . ':!*.lock' ':!LICENSE'"

run_check "3. no forbidden files tracked" \
    "git ls-files | grep -iE '${forbidden_paths}'"

run_check "4. clean working tree" \
    "git status --porcelain"

run_check "5. LICENSE matches the canonical Apache-2.0 text" \
    "license_integrity"

for pattern in ${ABSENT_PATTERNS+"${ABSENT_PATTERNS[@]}"}; do
    run_check "absent: ${pattern}" "git grep -ilE '${pattern}' -- . ':!infra/audit.sh'"
done

for pattern in ${PRESENT_PATTERNS+"${PRESENT_PATTERNS[@]}"}; do
    if git grep -qlE "${pattern}" -- . ':!infra/audit.sh'; then
        printf 'ok    present: %s\n' "${pattern}"
    else
        printf 'FAIL  present: %s (not found in tracked content)\n' "${pattern}"
        failures=$((failures + 1))
    fi
done

echo
if [ "$failures" -eq 0 ]; then
    echo "audit passed"
    exit 0
fi
echo "audit failed: ${failures} check(s)"
exit 1
