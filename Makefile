# Token Eye — 常用命令入口（无构建步骤，纯本地脚本）
#
#   make install   安装/更新插件到 ~/SwiftBar/（只需复制 token-eye.sh）
#   make test      单元测试
#   make lint      bash 语法 + Python 编译检查 + 版本号一致性 + ShellCheck（可用时）
#   make validate  JSON Schema + 跨端配置同步 + 配色对比度 + 节假日表覆盖当年
#   make check     全部检查（lint + test + validate），与 CI 主要步骤对齐
#   make holidays  更新中国法定节假日/调休表（holidays/<年>.json，每年公告后跑一次）

PYTHON ?= python3
SWIFTBAR_DIR ?= $(HOME)/SwiftBar
# 覆盖 Mac / Linux / scripts 全部 Python 源文件（含 linux/*.py、linux/scripts/*.py、add-provider.py）
PY_FILES := $(wildcard swiftbar/*.py scripts/*.py linux/*.py linux/scripts/*.py)
# bash 语法检查覆盖启动器、Linux 安装脚本与版本号校验脚本
SH_FILES := swiftbar/token-eye.sh linux/install.sh scripts/check-version.sh

.PHONY: install test lint validate check all holidays

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
	@for f in $(SH_FILES); do bash -n "$$f" || exit 1; done
	$(PYTHON) -m py_compile $(PY_FILES)
	@bash scripts/check-version.sh
	@if command -v shellcheck >/dev/null 2>&1; then \
		shellcheck -S warning swiftbar/token-eye.sh; \
		shellcheck -S error linux/install.sh; \
	else \
		echo "⚠️  shellcheck 未安装，跳过 ShellCheck（CI 会执行）"; \
	fi

validate:
	$(PYTHON) scripts/validate-schema.py
	$(PYTHON) scripts/check-config-sync.py
	$(PYTHON) scripts/sync-android-assets.py --check
	$(PYTHON) scripts/check-colors.py
	@$(PYTHON) -c 'import datetime, json, os; y = datetime.date.today().year; p = "holidays/%d.json" % y; assert os.path.isfile(p) and json.load(open(p, encoding="utf-8")).get("days"), "缺少当年节假日表 " + p; print("✅ holidays/%d.json 覆盖当年" % y)'

check: lint test validate
	@echo "✅ 全部检查通过"

holidays:
	$(PYTHON) scripts/update-holidays.py
