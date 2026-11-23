set positional-arguments
set shell := ["bash", "-uc"]

RENOVATE_IMAGE := "renovate/renovate:43.205.2@sha256:436f8141e24268342921d14aa7f5a22ef7f85e4e65ece12c3447769189ff3b10"

infra_override := env("ANSIBLE_AUTOMATIONS_DIR", "")
infra := if infra_override == "" { home_directory() / "Repos/Mine/ansible-automations" } else { join(invocation_directory(), infra_override) }
ansible_uv := "ANSIBLE_CONFIG=" + quote(infra / "ansible.cfg") + " uv run --directory ansible --frozen --project " + quote(infra)

# List available commands
help:
    @{{ quote(just_executable()) }} --justfile {{ quote(justfile()) }} --list

alias install-pre-commit := install-prek
alias pre-commit := prek

# Install prek hooks
install-prek:
    uvx prek install

# Run prek for all files
prek:
    uvx prek run --all-files

# Validate Renovate configuration
renovate-validate:
    docker run --rm --pull=always \
        --entrypoint renovate-config-validator \
        -v "$PWD:/repo:ro" -w /repo \
        {{ quote(RENOVATE_IMAGE) }}

# Run a local Renovate lookup
renovate-local:
    docker run --rm --pull=always \
        -v "$PWD:/repo:ro" -w /repo \
        -e LOG_LEVEL=info \
        -e RENOVATE_INTERNAL_CHECKS_FILTER=strict \
        -e RENOVATE_GITHUB_COM_TOKEN \
        {{ quote(RENOVATE_IMAGE) }} --platform=local --dry-run=lookup

# Manage this host's stack (up, down, pull, update, restart, prune)
local action:
    @bash scripts/docker-manage.sh "$1"

# Install the Ansible collections on coding
ansible-collections:
    @{{ ansible_uv }} ansible-galaxy collection install -r collections/requirements.yml

# Run a repository playbook from coding
ansible playbook *args:
    @{{ ansible_uv }} ansible-playbook "$@"

# Update the checkout, sync the environment, and apply Compose
ansible-deploy *args:
    @{{ ansible_uv }} ansible-playbook deploy.yml "$@"

# Run a fleet Compose action from coding
ansible-compose action *args:
    @{{ ansible_uv }} ansible-playbook docker_compose.yml "${@:2}" -e "task=$1"
