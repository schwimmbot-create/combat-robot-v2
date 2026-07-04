# Combat Robot v2 — cross-platform local development wrapper
#
# The real portability lives in tools/dev.py. This Makefile is a thin
# convenience layer for machines with make installed; Windows/macOS/Linux can
# also run `python tools/dev.py ...` directly.

PY      ?= $(shell command -v python3 2>/dev/null || command -v python 2>/dev/null || echo python)
DEV     := $(PY) tools/dev.py
ENV     ?= esp32-c3-devkitc-02
PORT    ?=
BAUD    ?= 115200
PORTARG := $(if $(PORT),--port $(PORT),)

.PHONY: help setup venv build flash monitor test test-output test-struct \
        test-preflash bench-scan bench-write ota upload-clean clean distclean info

help: ## Show this help
	@$(DEV) --help
	@echo ""
	@echo "Common targets: setup test build flash monitor bench-scan bench-write clean info"
	@echo "Use ENV=esp32-c3-devkitc-02-dev and PORT=COM6 or PORT=/dev/ttyACM0 as needed."

venv: setup ## Alias for setup

setup: ## Create project-local .venv with platformio + pytest + bleak
	$(DEV) setup

info: ## Show detected OS/tool/default-port info
	$(DEV) info

build: ## Build firmware (ENV=$(ENV))
	$(DEV) build --env $(ENV)

flash: ## Build + flash firmware (PORT defaults by OS; override with PORT=...)
	$(DEV) flash --env $(ENV) $(PORTARG)

monitor: ## Serial monitor, RTS/DTR held low (override PORT=... BAUD=...)
	$(DEV) monitor $(PORTARG) --baud $(BAUD)

test: ## Run all host-side tests
	$(DEV) test

test-output: ## output_config/web UI wiring tests
	$(DEV) test tests/integration/test_output_config.py -v

test-struct: ## v1.3 byte-identical regression guards
	$(DEV) test tests/regression/test_structure.py -v

test-preflash: ## pre-flash stop sign
	$(DEV) test tests/integration/test_pre_flash.py -v

bench-scan: ## BLE bench: scan for CombatRobot-v2 advertisement
	$(DEV) bench-scan

bench-write: ## BLE bench: write neutral synthetic frame (BENCH_MAC=...)
	$(DEV) bench-write $(if $(BENCH_MAC),--mac $(BENCH_MAC),)

ota: ## Upload local firmware.bin via web UI OTA (manual — open device AP)
	@test -f .pio/build/$(ENV)/firmware.bin || (echo "build first: make build" && exit 1)
	@echo "Open http://192.168.4.1 in browser, Settings tab, upload:"
	@ls -lh .pio/build/$(ENV)/firmware.bin

upload-clean: ## Remove uploaded .bin/log leftovers from repo root
	rm -f upload-*.log live-*.log hermes-verify-*.log build-*.log

clean: ## Remove PlatformIO build cache for ENV
	$(DEV) clean --env $(ENV)

distclean: ## Remove PlatformIO build cache + .venv + Python caches
	rm -rf .pio .venv components/**/__pycache__ tools/__pycache__ tests/**/__pycache__
