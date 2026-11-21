# Deploying Career Context Hub (hosted mode)

Hosted mode serves MCP over HTTPS at `/mcp`. Every request needs `Authorization: Bearer <token>`;
each token maps to exactly one user. Use a server you own personally; do not use an employer's.

## 1. Run it
    git clone <your repo> && cd career-hub
    export CAREER_HUB_ALLOWED_HOSTS=hub.example.com     # your real domain
    docker compose up -d --build
The app listens on 127.0.0.1:8000 only. Check: `curl http://127.0.0.1:8000/healthz`.

## 2. TLS reverse proxy (Caddy example)
    hub.example.com {
        reverse_proxy 127.0.0.1:8000
    }
Point the domain's DNS at the server and open only ports 80/443 in the firewall (on Oracle Cloud:
the VCN security list AND the instance firewall). Never expose port 8000 publicly.

## 3. Create users and tokens
    docker compose exec career-hub career-hub-admin create-user "Ada"
The token is printed once; only its hash is stored. Rotate with `rotate-token <id>`.

## 4. Connect a client (Claude Code example)
    claude mcp add --transport http career-hub https://hub.example.com/mcp \
        --header "Authorization: Bearer <token>"

## 5. Backups (do this before storing real data)
    docker compose exec career-hub career-hub-admin backup /data/backup-$(date +%F).db
Cron it daily and copy the files off the machine. Backups contain personal data: encrypt them and
restrict access.

## 6. Data rights
    career-hub-admin export <id> --out user.json     # data portability
    career-hub-admin delete-user <id> --yes          # permanent deletion
Also delete that user's rows from old backups when your retention policy requires it.

## Security checklist
- [ ] Domain + TLS working; port 8000 not reachable from the internet
- [ ] `CAREER_HUB_ALLOWED_HOSTS` set to your domain
- [ ] Tokens stored in a password manager, never in git or chat
- [ ] Daily backups tested by restoring one
- [ ] Keep the OS and the Docker image updated
- [ ] Before inviting others: privacy policy, deletion/export process, and a security review
Rate limits are per process and in memory (120 requests/min per user, 20 failed auths/min per IP).
Behind a proxy the "IP" is the proxy's unless forwarded headers are trusted.
