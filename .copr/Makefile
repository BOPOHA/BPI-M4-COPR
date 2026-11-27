# COPR's isolated, network-enabled SCM source worker only. Not a host setup target.
.PHONY: srpm
DNF ?= dnf
srpm:
	$(DNF) install -y python3 rpm-build rpkg gnupg2 curl git-core jq xz cpio util-linux
	./scripts/copr-srpm.bash --spec "$(spec)" --outdir "$(outdir)"
