.DEFAULT_GOAL := help
export PATH := $(CURDIR)/scripts/rpm-tools:$(PATH)
export PYTHONDONTWRITEBYTECODE := 1
JOBS ?= 8
PROFILE ?= server
.PHONY: help test checks srpms rpms clean clean-hard
help:
	@echo 'make srpms / rpms PROFILE=server|media JOBS=8; make test / checks'
srpms: srpm-board srpm-kernel-updates srpm-sd-boot
rpms: rpm-board rpm-kernel-updates rpm-sd-boot
srpm-module-checks:
	./scripts/prepare-module-check.bash
srpm-%:
	python3 -m bpi_packaging.rpm_packages $* --profile $(PROFILE) --srpm --jobs $(JOBS)
rpm-%:
	python3 -m bpi_packaging.rpm_packages $* --profile $(PROFILE) --jobs $(JOBS)
test:
	bash tests/check-emmc-clock.bash
	python3 -m unittest discover -s tests -v
checks:
	python3 -m bpi_packaging.rpm_packages checks --jobs $(JOBS)
clean:
	./scripts/clean-rpm-work.bash work/rpms out/rpms out/srpms
clean-hard:
	git clean -dffX
