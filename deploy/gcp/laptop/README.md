# Laptop controls for the demo VM

The commands the owner runs from a laptop to operate the public demo
(`docs/Deploy.md`). The working copy lives at `~/Desktop/mnemos-demo/` on the owner's
laptop; this folder is the record of it. Change the Desktop copy, then copy it here in
a PR, so the two stay identical.

Every gcloud call goes through `lib.sh`'s `g`, which pins the account and project.

| Command | Does |
|---|---|
| `./init` | checks gcloud and the login (logs in if needed), then prints the menu |
| `./up` | starts the VM, points the 4 hostnames at its new IP, waits until `/readyz` is ready |
| `./down` | deletes the DNS records, stops the VM |
| `./status` | read-only: VM state, IP, DNS on the authoritative server, certificate expiry, app ready? |
| `./extend` / `./extend N` / `./extend off` | shows, resets or cancels the 4-hour auto power-off (IST) |
| `./redeploy` / `./redeploy main` | on the VM: pull, rebuild (`--remove-orphans`), prune the build cache, wait until ready |
| `./ssh [cmd]` · `./logs [service]` | shell on the VM through IAP · follow container logs |
| `./guide` | opens `guide.html`, the visual version of all this |

The VM also writes its own DNS on boot and deletes it on shutdown
(`deploy/gcp/setup-vm-dns.sh`), so Start/Stop in the Cloud console works without these;
`up` and `down` doing the same is harmless.

`demo-password.txt`, if present on the laptop, is never copied here (`.gitignore`).
