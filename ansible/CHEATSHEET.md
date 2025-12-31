# Ansible Cheatsheet for Debian Host Management

## Prerequisites
1. **SSH Access**: Ensure you can SSH into your hosts (RPis, LXCs, VMs) as **root** from this machine.
   ```bash
   ssh-copy-id root@192.168.2.X
   ```
2. **Inventory**: Update `ansible/inventory.yaml` with the correct IP addresses of your hosts.

## Common Commands

### 1. Connectivity Check
Ping all hosts in the inventory to ensure Ansible can reach them.
```bash
ansible -i ansible/inventory.yaml all -m ping
```

### 2. Running a Playbook
Run the setup playbook to update the system, create user, and install Docker.
```bash
ansible-playbook -i ansible/inventory.yaml ansible/setup_lxc.yml
```
*If you need to provide a sudo password:*
```bash
ansible-playbook -i ansible/inventory.yaml ansible/setup_lxc.yml --ask-become-pass
```

### 3. Ad-Hoc Commands
Run a single command on all hosts without writing a playbook.

**Check disk usage:**
```bash
ansible -i ansible/inventory.yaml all -a "df -h"
```

**Check memory usage:**
```bash
ansible -i ansible/inventory.yaml all -a "free -m"
```

**Reboot all hosts:**
```bash
ansible -i ansible/inventory.yaml all -a "sudo reboot"
```

### 4. Limiting Execution
Run the playbook only on a specific host (e.g., `lxc1`).
```bash
ansible-playbook -i ansible/inventory.yaml ansible/setup_lxc.yml --limit lxc1
```

### 5. Syntax Check
Check your playbook for syntax errors before running.
```bash
ansible-playbook -i ansible/inventory.yaml ansible/setup_lxc.yml --syntax-check
```

### 6. Handling Private Repositories
If you are cloning a private GitHub repository, you need to authenticate.

**SSH Agent Forwarding**
This allows the RPi to use the SSH keys on your local machine.
1. Ensure your SSH key is added to your local agent:
   ```bash
   eval "$(ssh-agent -s)"

   ssh-add -L  # Check if key is listed
   ssh-add ~/.ssh/id_ed25519  # Add if missing
   ```
2. Enable forwarding in `ansible.cfg` (create if missing in `ansible/` folder):
   ```ini
   [ssh_connection]
   ssh_args = -o ForwardAgent=yes
   ```
   *Or pass it in the command line:*
   ```bash
   ansible-playbook -i ansible/inventory.yaml ansible/setup_lxc.yml --ssh-common-args='-o ForwardAgent=yes'
   ```

### 7. Deploying Updates
To pull the latest code and restart containers:
```bash
ansible-playbook -i ansible/inventory.yaml ansible/deploy.yml --ssh-common-args='-o ForwardAgent=yes'
```

## Directory Structure
- `inventory.yaml`: List of your servers (RPis).
- `setup_lxc.yml`: The script (playbook) that defines what to install/configure.
