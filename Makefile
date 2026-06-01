# Oneshell means one can run multiple lines in a recipe in the same shell, so one doesn't have to
# chain commands together with semicolon
.ONESHELL:
SHELL=/bin/bash

.PHONY: help install-prek install-pre-commit prek pre-commit
.DEFAULT_GOAL=help

RENOVATE_IMAGE := renovate/renovate:43.205.2@sha256:436f8141e24268342921d14aa7f5a22ef7f85e4e65ece12c3447769189ff3b10

help:
	@grep -E '^[0-9a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) |\
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m\
			%s\n", $$1, $$2}'

## If .env file exists, include it and export its variables
ifeq ($(shell test -f .env && echo 1),1)
	include .env
	export
endif

install-prek: ## Install prek hooks
	uvx prek install

install-pre-commit: install-prek ## Alias for install-prek

prek: ## Run prek for all files
	uvx prek run --all-files

pre-commit: prek ## Alias for prek

renovate-validate: ## Validate Renovate config
	docker run --rm --pull=always \
		--entrypoint renovate-config-validator \
		-v "$(CURDIR):/repo:ro" \
		-w /repo \
		$(RENOVATE_IMAGE)

renovate-local: ## Run Renovate local lookup dry-run
	docker run --rm --pull=always \
		-v "$(CURDIR):/repo:ro" \
		-w /repo \
		-e LOG_LEVEL=info \
		-e RENOVATE_INTERNAL_CHECKS_FILTER=strict \
		-e RENOVATE_GITHUB_COM_TOKEN \
		$(RENOVATE_IMAGE) \
		--platform=local \
		--dry-run=lookup
