# Oneshell means one can run multiple lines in a recipe in the same shell, so one doesn't have to
# chain commands together with semicolon
.ONESHELL:
SHELL=/bin/bash

.PHONY: help install-prek install-pre-commit prek pre-commit
.DEFAULT_GOAL=help

help:
	@grep -E '^[0-9a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) |\
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m\
			%s\n", $$1, $$2}'

## If .env file exists, include it and export its variables
# ifeq ($(shell test -f .env && echo 1),1)
#     include .env
#     export
# endif

install-prek: ## Install prek hooks
	uvx prek install

install-pre-commit: install-prek ## Alias for install-prek

prek: ## Run prek for all files
	uvx prek run --all-files

pre-commit: prek ## Alias for prek
