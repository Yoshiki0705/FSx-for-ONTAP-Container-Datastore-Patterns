# Quality gates

Every gate is a `make` target. CI calls those targets rather than invoking tools
directly, and the path lists live in Makefile variables, so a local run and a CI
run inspect the same tree with the same tool version.

```bash
make install    # .venv を作り requirements-dev.txt を固定版で導入
make gates      # cfn-lint + headings + role-labels
make ci         # gates の別名
```

## Gate inventory

| Target | Tool | Scope variable |
|---|---|---|
| `cfn-lint` | cfn-lint | `TEMPLATE_GLOB` (`templates/*.yaml`) |
| `headings` | `tools/check_heading_style.py` (selftest, then scan) | `HEADING_CHECK`; walk scope is the script's `SKIP` set |
| `role-labels` | `tools/check_role_labels.py` (selftest, then scan) | headings and leading bold labels in `*.md`, excluding code fences |

## Additional checks (run before publishing docs)

These are not yet wired into a `make` target here; run them by hand on changed
docs until the CI workflows are ported from the hub template.

```bash
# Naming: no FSxN / bare FSx / FSx ONTAP outside allow:naming
grep -nE '\bFSxN\b|FSx ONTAP' <changed.md>
# Vendor neutrality: no superiority claims
grep -nE '最強|最速|fastest|is better than|競合ツール|優位性' <changed.md>
# JA/EN parity: matching '##' counts
grep -c '^##' docs/ja/<f>.md docs/en/<f>.md
# Secrets
gitleaks detect --no-git --source .
```

## Tool versions

`requirements-dev.txt` holds what the gates need, exact-pinned. Widening to a
range lets local and CI diverge.

## Pitfalls carried over from the hub template

| Pitfall | Root cause | Resolution |
|---|---|---|
| A `make` target named after an existing directory silently no-ops | make treats it as an up-to-date file target | All targets declared `.PHONY` |
| A failing gate hidden by a pipe | `make gates \| tail && git commit` returns tail's status, so `&&` never sees the failure | Read the exit status directly; do not pipe the gate when checking pass/fail |
| cfn-lint warnings read as a pass | cfn-lint exits 4 on warnings, which fails the gate | Treat any non-zero exit as failure; fix warnings (e.g. avoid empty defaults on typed params) |
| A control test appeared to prove a scanner broken | a planted value was an allowlisted placeholder | Control inputs must be values the rules actually reject |

## Supply-chain (to port when CI is added)

This repository is public. Before adding GitHub Actions workflows, follow the
supply-chain-security steering: pin actions by SHA, add zizmor / gitleaks /
OpenSSF Scorecard, exact-pin dependencies, add Renovate, and a PR-title check
(conventional commits). The hub and the sibling migration repository carry
workflow templates to adapt.
