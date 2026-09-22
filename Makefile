# Quality gates for FSx-for-ONTAP-Container-Datastore-Patterns.
#
# Two invariants this file exists to hold:
#
# 1. Every target is declared in .PHONY. A target named after a directory that
#    exists on disk (docs, templates) is otherwise treated by make as an
#    up-to-date file, so make prints "up to date" and never runs the recipe.
# 2. Path lists live in variables here and CI calls these targets, so local and
#    CI cannot end up inspecting different trees.
#
# Tools resolve from .venv when it exists, otherwise from PATH.

VENV      := .venv
VENV_BIN  := $(VENV)/bin
tool       = $(if $(wildcard $(VENV_BIN)/$(1)),$(VENV_BIN)/$(1),$(1))

PYTHON    := $(call tool,python)
PIP       := $(call tool,pip)
CFN_LINT  := $(call tool,cfn-lint)

TEMPLATE_GLOB := templates/*.yaml
HEADING_CHECK := tools/check_heading_style.py

.DEFAULT_GOAL := help

.PHONY: help
help: ## このファイルのターゲット一覧
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## .venv を作り cfn-lint を導入
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements-dev.txt

.PHONY: cfn-lint
cfn-lint: ## CloudFormation テンプレートの lint
	$(CFN_LINT) $(TEMPLATE_GLOB)

.PHONY: headings
headings: ## 日本語の節見出しが体言止めか（本検査の前に自己テストを走らせる）
	@$(PYTHON) $(HEADING_CHECK) --selftest >/dev/null
	$(PYTHON) $(HEADING_CHECK)

.PHONY: role-labels
role-labels: ## ラベルが職種名を名乗っていないか（所見ではなくラベルだけの問題）
	$(PYTHON) tools/check_role_labels.py --selftest >/dev/null
	$(PYTHON) tools/check_role_labels.py

.PHONY: gates
gates: cfn-lint headings role-labels ## どこでも走る検査（CI とフックが呼ぶ）

.PHONY: ci
ci: gates ## CI が呼ぶ集約ターゲット

.PHONY: all
all: ci ## ci の別名
