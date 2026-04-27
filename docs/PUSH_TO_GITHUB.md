# Pushing this repo to GitHub

Step-by-step. Total time: ~2 minutes.

## 1. Create the empty repo on GitHub

Go to <https://github.com/new> and fill in:

- **Owner:** nowayman22
- **Repository name:** `flowchart-automation`
- **Description:** *Visual, node-based automation tool for image/color/OCR-driven task flows.*
- **Public** or **Private** — your call. Public is fine; the code is already MIT-licensed in the scaffold.
- **Do NOT** tick "Initialize with README", "Add .gitignore", or "Add license". The scaffold already has all three — adding GitHub's would create a merge conflict on first push.

Click **Create repository**.

## 2. Push from your machine

Open a terminal in the unzipped `flowchart-automation/` folder and run:

```bash
git init
git add .
git commit -m "Initial commit: Rev. 65 + scaffold"
git branch -M main
git remote add origin https://github.com/nowayman22/flowchart-automation.git
git push -u origin main
```

If 2FA / personal-access-tokens trip you up on the `push`, GitHub's docs walk through it: <https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens>. The short version: generate a fine-grained PAT with `Contents: Read and write` for this repo, paste it as the password when git prompts.

## 3. First release (optional, but the CI builds an .exe for you)

Once pushed:

```bash
git tag v0.66.0
git push origin v0.66.0
```

The `build-windows` job in `.github/workflows/ci.yml` triggers on tags starting with `v` and attaches a `FlowchartAutomation.exe` to the GitHub Release. First run takes ~5 minutes.

## 4. Tidy-up after first push

A few things worth doing in the GitHub web UI:

- **Settings → General → Features:** turn off Wiki and Projects unless you want them.
- **Settings → Branches → Branch protection rules:** add a rule for `main` requiring CI to pass before merging. Optional but recommended once you're past v0.66.0.
- **About panel** (top-right of the repo page → ⚙): paste the description, add topics like `automation`, `tkinter`, `opencv`, `pyautogui`, `flowchart`.
- **Pin issues** for the Phase 1 / Phase 2 tasks from `docs/CODE_REVIEW.md` so the roadmap is visible.

## 5. After it's pushed

The CI workflow will run on every push to `main` and every PR. The first run will fail on `ruff check .` because the legacy `FlowchartClickerApp66.py` has style issues — `pyproject.toml` already excludes it from ruff (`extend-exclude`), so you should actually be fine. If anything else fails, paste the action log and I'll help debug.
