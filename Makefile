# Combat Robot v2 — local development wrapper
#
# All commands run from this Makefile's directory and use the project-local
# Python virtualenv at .venv/ (created by `make setup`). The venv holds
# platformio + pytest + bleak — the only host-side tools needed for the
# fast feedback loop. ESP-IDF + xtensa toolchain are downloaded by
# PlatformIO on first build, into ~/.platformio/packages/.
#
# Flash + monitor ports are passed as env vars; defaults are COM6 (Kevin's
# Windows laptop) and /dev/ttyACM0 (the Linux build box this Makefile was
# authored on).

PY      := .venv/bin/python
PIO     := .venv/bin/pio
PYTEST  := .venv/bin/pytest
BLE_BENCH := tools/pc_ble_bench.py

ENV     ?= esp32-c3-devkitc-02
PORT    ?= /dev/ttyACM0
BAUD    ?= 115200

.PHONY: help setup venv build flash monitor test test-output test-struct \
        test-preflash bench-scan bench-clean ota upload-clean clean distclean

help: ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

venv: ## Create project-local venv with platformio + pytest + bleak
	@if [ ! -d .venv ]; then uv venv .venv --python python3.12; fi
	uv pip install --python $(PY) platformio pytest bleak

setup: venv ## Full first-run setup (venv + sanity checks)
	@$(PIO) --version
	@$(PYTEST) --version
	@$(PY) -c "import bleak; print('bleak', bleak.__version__ if hasattr(bleak, '__version__') else 'installed')"

build: ## Build firmware (env=$(ENV))
	$(PIO) run -e $(ENV)

flash: ## Build + flash firmware to $(PORT)
	$(PIO) run -e $(ENV) -t upload --upload-port $(PORT)

monitor: ## Serial monitor on $(PORT) @ $(BAUD) (RTS/DTR held low to avoid spurious resets)
	$(PIO) device monitor -p $(PORT) -b $(BAUD) --rts 0 --dtr 0 --no-reconnect

test: ## Run all host-side tests (~1s, static C-source parsers)
	$(PYTEST) tests/ -q

test-output: ## output_config chunk 1+2+3+4+5 wiring tests
	$(PYTEST) tests/integration/test_output_config.py -v

test-struct: ## v1.3 byte-identical regression guards (skips if v1 reference absent)
	$(PYTEST) tests/regression/test_structure.py -v

test-preflash: ## pre-flash stop sign
	$(PYTEST) tests/integration/test_pre_flash.py -v

bench-scan: ## BLE bench: scan for CombatRobot-v2 advertisement
	$(PY) $(BLE_BENCH) scan

bench-write: ## BLE bench: write neutral synthetic frame (MAC via BENCH_MAC=...)
	@test -n "$(BENCH_MAC)" || (echo "BENCH_MAC=<aa:bb:cc:dd:ee:ff> required" && exit 1)
	$(PY) $(BLE_BENCH) write $(BENCH_MAC) --standard-frame --response

ota: ## Upload local .pio/build/$(ENV)/firmware.bin via web UI OTA (manual — open device AP)
	@test -f .pio/build/$(ENV)/firmware.bin || (echo "build first: make build" && exit 1)
	@echo "Open http://192.168.4.1 in browser, Settings tab, upload:"
	@ls -lh .pio/build/$(ENV)/firmware.bin

upload-clean: ## Remove uploaded .bin leftovers from repo root (keeps repo tidy)
	rm -f upload-*.log live-*.log hermes-verify-*.log

clean: ## Remove PlatformIO build cache
	$(PIO) run -e $(ENV) -t clean

distclean: ## Remove .pio build cache + .venv + __pycache__
	rm -rf .pio .venv components/**/__pycache__ tools/__pycache__ tests/**/__pycache__