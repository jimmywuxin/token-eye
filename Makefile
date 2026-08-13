# Token Eye — 常用命令入口（无构建步骤，纯本地脚本）
#
#   make install   安装/更新插件到 ~/SwiftBar/（只需复制 token-eye.sh）
#   make test      单元测试
#   make lint      bash 语法 + Python 编译检查
#   make validate  JSON Schema + 配色对比度检查
#   make check     全部检查（lint + test + validate）

PYTHON ?= python3
SWIFTBAR_DIR ?= $(HOME)/SwiftBar
PY_FILES := swiftbar/token_eye.py scripts/check-colors.py scripts/refresh-mimo-cookie.py scripts/validate-schema.py

.PHONY: install test lint validate check all

all: check

install:
	@mkdir -p "$(SWIFTBAR_DIR)"
	cp swiftbar/token-eye.sh "$(SWIFTBAR_DIR)/token-eye.sh"
	chmod +x "$(SWIFTBAR_DIR)/token-eye.sh"
	@echo "✅ 已安装到 $(SWIFTBAR_DIR)/token-eye.sh"
	@echo "   提示: providers.json 与核心逻辑（swiftbar/token_eye.py）仍从项目目录自动读取，无需复制"

test:
	$(PYTHON) -m unittest discover -s tests -v

lint:
	bash -n swiftbar/token-eye.sh
	$(PYTHON) -m py_compile $(PY_FILES)

validate:
	$(PYTHON) scripts/validate-schema.py
	$(PYTHON) scripts/check-colors.py

check: lint test validate
	@echo "✅ 全部检查通过"
