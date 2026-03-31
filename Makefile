# Oneshell means one can run multiple lines in a recipe in the same shell, so one doesn't have to
# chain commands together with semicolon
.ONESHELL:
SHELL=/bin/bash

.PHONY: help lint format pre-commit
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

pre-commit: ## Run pre-commit for all package files
	pre-commit run --all-files
