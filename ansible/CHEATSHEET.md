# Ansible Cheatsheet for Raspberry Pi Management

## Prerequisites
1. **SSH Access**: Ensure you can SSH into your Raspberry Pis from this machine.
   ```bash
   ssh-copy-id ilker@192.168.1.X
   ```
2. **Inventory**: Update `ansible/inventory.ini` with the correct IP addresses of your Pis.

## Common Commands

### 1. Connectivity Check
Ping all hosts in the inventory to ensure Ansible can reach them.
```bash
ansible -i ansible/inventory.ini all -m ping
```

### 2. Running a Playbook
Run the setup playbook to update the system and install Docker.
```bash
ansible-playbook -i ansible/inventory.ini ansible/setup_rpi.yml
```
*If you need to provide a sudo password:*
```bash
ansible-playbook -i ansible/inventory.ini ansible/setup_rpi.yml --ask-become-pass
```

### 3. Ad-Hoc Commands
Run a single command on all Pis without writing a playbook.

**Check disk usage:**
```bash
ansible -i ansible/inventory.ini rpis -a "df -h"
```

**Check memory usage:**
```bash
ansible -i ansible/inventory.ini rpis -a "free -m"
```

**Reboot all Pis:**
```bash
ansible -i ansible/inventory.ini rpis -a "sudo reboot"
```

### 4. Limiting Execution
Run the playbook only on a specific host (e.g., `rpi1`).
```bash
ansible-playbook -i ansible/inventory.ini ansible/setup_rpi.yml --limit rpi1
```

### 5. Syntax Check
Check your playbook for syntax errors before running.
```bash
ansible-playbook -i ansible/inventory.ini ansible/setup_rpi.yml --syntax-check
```

### 6. Handling Private Repositories
If you are cloning a private GitHub repository, you need to authenticate.

**SSH Agent Forwarding**
This allows the RPi to use the SSH keys on your local machine.
1. Ensure your SSH key is added to your local agent:
   ```bash
   ssh-add -L  # Check if key is listed
   ssh-add ~/.ssh/id_rsa  # Add if missing
   ```
2. Enable forwarding in `ansible.cfg` (create if missing in `ansible/` folder):
   ```ini
   [ssh_connection]
   ssh_args = -o ForwardAgent=yes
   ```
   *Or pass it in the command line:*
   ```bash
   ansible-playbook -i ansible/inventory.ini ansible/setup_rpi.yml --ssh-common-args='-o ForwardAgent=yes'
   ```

### 7. Deploying Updates
To pull the latest code and restart containers:
```bash
ansible-playbook -i ansible/inventory.ini ansible/deploy.yml --ssh-common-args='-o ForwardAgent=yes'
```

## Directory Structure
- `inventory.ini`: List of your servers (RPis).
- `setup_rpi.yml`: The script (playbook) that defines what to install/configure.
