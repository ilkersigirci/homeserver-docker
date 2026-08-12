# Proxmox Backup Client

This image packages Proxmox's official `proxmox-backup-client` and uses it as
the image entrypoint. The repository's one-shot backup command is defined in
[`apps/pbs-client-hs.yml`](../../apps/pbs-client-hs.yml).

Run the configured backup with:

```bash
docker compose --project-name pbs-client --profile maintenance --env-file .env \
  -f apps/pbs-client-hs.yml run --rm pbs-client
```

Arguments after the service name replace the configured backup command. For
example, list snapshots with:

```bash
docker compose --project-name pbs-client --profile maintenance --env-file .env \
  -f apps/pbs-client-hs.yml run --rm pbs-client snapshot list
```

Use the same options with `down` after direct runs to remove the one-off project
network. The repository's
[`docker-client.sh`](../../scripts/backup/pbs/docker-client.sh) handles this
cleanup automatically.

## PBS server setup

1. Create or select a datastore. Create the namespace configured by
    `PBS_NAMESPACE` before the first backup, including any parent namespace;
    the Compose default is `hosts/<hostname>`. Do this as a PBS administrator so
    the backup token does not need namespace-management privileges.
2. Create a dedicated PBS user and API token. Run the following on the PBS
    server as root, replacing `backupstore` and `hosts/nas` as needed:

    ```bash
    PBS_STORE=backupstore
    PBS_NAMESPACE=hosts/nas
    PBS_USER_ID=docker-backup@pbs
    PBS_TOKEN_NAME=docker-client
    PBS_TOKEN_ID="${PBS_USER_ID}!${PBS_TOKEN_NAME}"
    PBS_ACL_PATH="/datastore/${PBS_STORE}/${PBS_NAMESPACE}"

    proxmox-backup-manager user create "$PBS_USER_ID"
    proxmox-backup-manager user generate-token "$PBS_USER_ID" "$PBS_TOKEN_NAME"
    proxmox-backup-manager acl update "$PBS_ACL_PATH" DatastoreBackup --auth-id "$PBS_USER_ID"
    proxmox-backup-manager acl update "$PBS_ACL_PATH" DatastoreBackup --auth-id "$PBS_TOKEN_ID"
    proxmox-backup-manager user permissions "$PBS_TOKEN_ID" --path "$PBS_ACL_PATH"
    ```

    Save the generated token secret immediately; PBS displays it only once.
    Tokens have permissions independent of their owner and their effective
    permissions are the intersection of both, which is why both ACL entries are
    required. `DatastoreBackup` is sufficient for backups and restores owned by
    this identity. Grant the role at `/datastore/<store>` instead only when the
    identity must access multiple namespaces in that datastore.
3. Allow the Docker host to reach the PBS API, normally TCP port `8007`, and
    ensure the hostname in `PBS_SERVER` resolves to the server. For a
    self-signed certificate, obtain the SHA-256 fingerprint with:

    ```bash
    proxmox-backup-manager cert info
    ```

    A publicly trusted certificate does not require `PBS_FINGERPRINT`. Update
    the configured fingerprint whenever the PBS certificate changes.

## Client values

Set the Compose variables to the matching PBS values:

| Compose variable | Value |
| --- | --- |
| `PBS_SERVER` | PBS hostname |
| `PBS_PORT` | PBS API port; defaults to `8007` |
| `PBS_DATASTORE` | Datastore name, such as `backupstore` |
| `PBS_NAMESPACE` | Existing namespace, such as `hosts/nas` |
| `PBS_AUTH_ID` | Full token ID, such as `docker-backup@pbs!docker-client` |
| `PBS_PASSWORD` | One-time secret returned when the token was created |
| `PBS_FINGERPRINT` | PBS certificate fingerprint, or empty for trusted TLS |

For encrypted backups, keep `encryption-key.json` in the host directory mounted
at `/home/pbs/.config/proxmox-backup` and set `PBS_ENCRYPTION_PASSWORD` to its
passphrase. Keep an offline recovery copy of that key: PBS cannot recover
client-side encrypted data without it. The mounted directory must be accessible
to the configured `PUID:PGID`.

## References

- [Backup Client Usage](https://pbs.proxmox.com/docs/backup-client.html)
- [PBS User Management and API Tokens](https://pbs.proxmox.com/docs/user-management.html)
