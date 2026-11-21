# Releasing

Package name on PyPI: **career-context-hub** (import name `career_hub`). Commands installed:
`career-context-hub` (alias `career-hub`) and `career-hub-admin`.

## One-time setup
1. Create the GitHub repo `recscse/career-hub` (public) and push `main`.
2. On pypi.org (your personal account, 2FA on): *Your projects -> Publishing -> Add a pending publisher*
   - PyPI project name: `career-context-hub`
   - Owner: `recscse`, Repository: `career-hub`, Workflow: `release.yml`, Environment: `pypi`
3. On GitHub: *Settings -> Environments -> New environment* named `pypi`. Add yourself as a required
   reviewer so a release needs your click.
4. Packages appear under the repo's *Packages* section after the first tagged release (Docker image).
   Set the image's visibility to Public in *Package settings* if you want others to pull it.

## Each release
1. Update `version` in `pyproject.toml` and add a section to `CHANGELOG.md`.
2. If the database schema changed: update `SCHEMA` **and** append a migration to `MIGRATIONS` in `db.py`
   (never edit released entries).
3. `uv run pytest`, then commit and `git tag v0.1.1 && git push --tags`.
4. The workflows test, build, publish to PyPI, create the GitHub release and push the Docker image.

## Try a build locally
    uv build
    uv run --isolated --no-project --with dist/*.whl career-hub-admin --help
