# Thin delegating wrapper. The real targets live in source_code/Makefile.
# This keeps `make ...` working from the repo root (and the loop's `cwd=ROOT`
# make calls) without duplicating the target definitions.
.PHONY: help venv test-unit test-e2e test-security build build-images chart lint \
        prepull deploy verify clean demo-run

help venv test-unit test-e2e test-security build build-images chart lint \
     prepull deploy verify clean demo-run:
	@$(MAKE) -f source_code/Makefile $@
