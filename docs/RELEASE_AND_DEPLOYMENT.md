# Project Gwala Release And Deployment

Project Gwala uses a two-step release boundary:

```text
CODEX CHANGE
-> LOCAL TEST
-> RELEASE_GWALA
-> GITHUB
-> DEPLOY_LATEST
-> VPS ASSURANCE
```

## Local Release

Run releases from the repository root on `main`:

```bash
./release_gwala.sh "Commit message"
```

The script:

- verifies it is running from the Project Gwala repository;
- verifies `main`;
- verifies `origin` points to the private `project-gwala` GitHub repository;
- audits non-ignored files for protected paths and likely secrets before staging;
- runs syntax validation without writing `__pycache__`;
- runs focused safety tests;
- stages non-ignored repository changes while excluding secrets, logs, runtime data, and generated active/archive option-chain data;
- audits staged files again;
- shows a concise staged summary;
- commits and pushes `main` to `origin`.

The script never force-pushes, never resets or discards local changes, never deploys to the VPS, and never prints secret values.

## Protected Local Files

These files and directories are release-blocked or staging-excluded:

- `.env`
- `.webull_tokens/`
- `webull_data_sdk.log`
- `config/gwala.env`
- `config/webull_tokens/`
- `logs/`
- `backups/`
- root-level runtime files under `data/` such as CSV, JSON, log, database, and parquet artifacts
- `data/incidents/`
- generated option-chain CSVs under `data/options_chains/`
- generated option-chain active/archive directories

Source files such as `data/*.py` and option-chain templates under `data/options_chains/templates/` remain releasable.

## VPS Deployment

After the Mac release succeeds, deploy from the VPS as a separate approval step:

```bash
sudo /srv/projects/gwala/deploy_latest.sh
```

The VPS deployment flow remains:

```text
fetch origin
-> require clean VPS worktree
-> fast-forward main
-> Docker build
-> refresh host systemd health
-> refresh host Docker health
-> runtime assurance
-> report deployed commit
```

Do not SSH or deploy automatically from the Mac release script. GitHub release and VPS deployment remain separate controls.
