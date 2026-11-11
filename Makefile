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
AI_STYLE_CHECK := tools/ai_style_rules.py
AI_STYLE_PATHS := AGENTS.md README.md README.en.md docs/

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

.PHONY: ai-style
ai-style: ## AI 調の兆候を検査（fail tier で落とす。先に件数表を出す）
	@$(PYTHON) $(AI_STYLE_CHECK) --selftest >/dev/null
	@$(PYTHON) $(AI_STYLE_CHECK) $(AI_STYLE_PATHS) --summary
	$(PYTHON) $(AI_STYLE_CHECK) $(AI_STYLE_PATHS) --fail

.PHONY: test
test: ## ai-style 検出器の stdlib unittest
	$(PYTHON) -m unittest tools.test_ai_style

.PHONY: diagram-fonts
diagram-fonts: ## 図のラベルが可読性の下限を満たすか（自己テストを先に走らせる）
	@$(PYTHON) tools/check_diagram_fonts.py --selftest >/dev/null
	@$(PYTHON) tools/check_diagram_fonts.py

.PHONY: diagram-flow
diagram-flow: ## 図が右と下へ読めるか、ラベルがアイコンの下にあるか
	@$(PYTHON) tools/check_diagram_flow.py --selftest >/dev/null
	@$(PYTHON) tools/check_diagram_flow.py

# 次の 2 つは gates に入れない。AWS Architecture Icons のパッケージ（四半期ごとの配布、
# コミットしない）と draw.io CLI が要るため。コミットするのは生成物の .drawio と書き出した画像で、
# 上の 2 つの検査はそれを読む。
.PHONY: diagrams
diagrams: ## .drawio を再生成し SVG と PNG を書き出す（AWS アイコンのパッケージが要る）
	@$(PYTHON) tools/build_diagrams.py --write --export

.PHONY: diagrams-check
diagrams-check: ## コミット済みの図が仕様と一致するか（AWS アイコンのパッケージが要る）
	@$(PYTHON) tools/build_diagrams.py --check

.PHONY: gates
gates: cfn-lint headings role-labels diagram-fonts diagram-flow ai-style test ## どこでも走る検査（CI とフックが呼ぶ）

.PHONY: ci
ci: gates ## CI が呼ぶ集約ターゲット

.PHONY: all
all: ci ## ci の別名
