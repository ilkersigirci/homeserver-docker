# Ansible Cheatsheet for Debian Host Management

## Prerequisites
1. **SSH Access**: Ensure you can SSH into your hosts (RPis, LXCs, VMs) as **root** from this machine.
   ```bash
   ssh-copy-id root@192.168.2.X
   ```
2. **Inventory**: Update `./inventory/hosts.yaml` with the correct IP addresses of your hosts.

## Common Commands

### 0. Install Requirements (Ansible Galaxy collections)
Install the collections listed in `./collections/requirements.yaml` (e.g., `ansible.posix`).
```bash
ansible-galaxy collection install -r ./collections/requirements.yaml
```

### 1. Connectivity Check
Ping all hosts in the inventory to ensure Ansible can reach them.
```bash
ansible -i ./inventory/hosts.yaml all -m ping
```

### 2. Running a Playbook
Run the setup playbook to update the system, create user, and install Docker.
```bash
ansible-playbook -i ./inventory/hosts.yaml ./playbooks/setup_debian.yml
```
*If you need to provide a sudo password:*
```bash
ansible-playbook -i ./inventory/hosts.yaml ./playbooks/setup_debian.yml --ask-become-pass
```

### 3. Ad-Hoc Commands
Run a single command on all hosts without writing a playbook.

**Check disk usage:**
```bash
ansible -i ./inventory/hosts.yaml all -a "df -h"
```

**Check memory usage:**
```bash
ansible -i ./inventory/hosts.yaml all -a "free -m"
```

**Reboot all hosts:**
```bash
ansible -i ./inventory/hosts.yaml all -a "sudo reboot"
```

### 4. Limiting Execution
Run the playbook only on a specific host (e.g., `lxc1`).
```bash
ansible-playbook -i ./inventory/hosts.yaml ./playbooks/setup_debian.yml --limit lxc1
```

### 5. Syntax Check
Check your playbook for syntax errors before running.
```bash
ansible-playbook -i ./inventory/hosts.yaml ./playbooks/setup_debian.yml --syntax-check
```

### 6. Handling Private Repositories
If you are cloning a private GitHub repository, you need to authenticate.

**SSH Agent Forwarding**
This allows your other machines to use the SSH keys on your local machine.
1. (Alternative) Add your local agent using local `ssh-agent`:
   ```bash
   eval "$(ssh-agent -s)"

   ssh-add -L  # Check if key is listed
   ssh-add ~/.ssh/id_ed25519  # Add if missing
   ```
   *Tip: To avoid running this every time, add the following to your `~/.bashrc` or `~/.zshrc`:*
   ```bash
   if [ -z "$SSH_AUTH_SOCK" ]; then
      eval "$(ssh-agent -s)" > /dev/null
      ssh-add ~/.ssh/id_ed25519 2> /dev/null
   fi
   ```
2. Use `ssh-agent` of Unofficial Bitwarden cli `rbw` (recommended for better security):
   ```bash
   if [ -z "$XDG_RUNTIME_DIR" ]; then
      export XDG_RUNTIME_DIR="/run/user/$(id -u)"
   fi
   export SSH_AUTH_SOCK="$XDG_RUNTIME_DIR/rbw/ssh-agent-socket"
   ```

3. Enable forwarding in `ansible.cfg`:
   ```ini
   [ssh_connection]
   ssh_args = -o ForwardAgent=yes
   ```
   *Or pass it in the command line:*
   ```bash
   ansible-playbook -i ./inventory/hosts.yaml ./playbooks/setup_debian.yml --ssh-common-args='-o ForwardAgent=yes'
   ```

### 7. Deploying Updates
To pull the latest code and restart containers:
```bash
ansible-playbook -i ./inventory/hosts.yaml ./playbooks/deploy.yml --ssh-common-args='-o ForwardAgent=yes'
```

## Directory Structure

- `inventory/`: Contains host inventory files.
- `playbooks/`: Contains Ansible playbooks for various tasks.
- `roles/`: Contains reusable Ansible roles (e.g., `common`, `docker
`, `lxc`).
- `ansible.cfg`: Ansible configuration file.

## Additional Tips

- Use `--check` with playbooks to perform a dry run without making changes.
- Use `--diff` to see what changes would be made by the playbook.