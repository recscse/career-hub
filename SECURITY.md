# Security

This project stores personal career data (resumes can contain contact details).

## Reporting a vulnerability
Please do not open a public issue. Use GitHub's "Report a vulnerability" (private security advisory)
on this repository.

## Notes for operators
- Local mode keeps everything in a SQLite file on your machine; nothing is sent anywhere except the
  public job-board and GitHub requests you ask for.
- Hosted mode requires TLS (reverse proxy), per-user tokens kept secret, and backups you encrypt.
  See `DEPLOY.md`.
- Job postings and resume text are untrusted input for your AI client; the server labels them as data.
