.DEFAULT_GOAL := help
export PYTHONDONTWRITEBYTECODE := 1
COPR_CLI ?= copr-cli
PACKAGE ?= bpi-m4-kernel
PROJECT := $(shell jq -r .project packaging/copr-scm.json)
.PHONY: help configure build checks test
help:
	@echo 'make configure; make build PACKAGE=bpi-m4-kernel; make checks; make test'
	@echo 'Builds pull Git on COPR (fedora-45-aarch64). test runs local regressions.'
configure:
	COPR_CLI="$(COPR_CLI)" ./scripts/configure-copr-scm.bash
build:
	@jq -e --arg name "$(PACKAGE)" '.packages | any(.name == $$name)' packaging/copr-scm.json >/dev/null
	"$(COPR_CLI)" build-package --nowait -r fedora-45-aarch64 --name "$(PACKAGE)" "$(PROJECT)"
checks:
	$(MAKE) build PACKAGE=bpi-m4-build-checks
test:
	bash tests/check-emmc-clock.bash
	python3 -m unittest discover -s tests -v
