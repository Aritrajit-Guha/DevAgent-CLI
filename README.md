# DevAgent CLI

DevAgent CLI is a local-first agentic developer assistant. It binds to a project
folder, indexes source code, answers repo-aware questions, proposes controlled
code edits, and automates common Git workflows.

## Install

Prerequisites:

- Python 3.11+
- Git
- GitHub CLI (`gh`) for publishing local projects to GitHub
- Gemini API key for AI-backed chat, embeddings, edit proposals, and guidance
- Optional: Visual Studio Code, Node.js LTS

Create a virtual environment and install the CLI:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

For AI-backed chat, edit proposals, embeddings, and commit messages:

```bash
copy .env.example .env
# set GEMINI_API_KEY in .env
```

## Commands

```bash
devagent --help
devagent new project
devagent workspace bind .
devagent workspace status
devagent setup clone https://github.com/user/repo
devagent clone https://github.com/user/repo
devagent setup publish .
devagent index
devagent chat "Explain the project structure"
devagent packages
devagent git
devagent run
devagent run start
devagent run start --open-browser
devagent run save "I order you to start in the name of jesus"
devagent git add
devagent git commit
devagent git pr preview
devagent edit "Add logging to login function"
devagent git status
devagent git branch create feature/login
devagent watch
devagent inspect
```

## Feature Branch Plan

The intended development flow is one branch per feature, then merge into `main`:

1. `codex/project-scaffold`
2. `codex/workspace-binding`
3. `codex/smart-project-setup`
4. `codex/repo-aware-chat`
5. `codex/code-action-agent`
6. `codex/git-assistant`
7. `codex/commit-generator`
8. `codex/watch-mode`
9. `codex/safety-insights`

## MVP Notes

- The indexer stores local JSON records in your user-level DevAgent cache.
- If Gemini credentials are available, embeddings and LLM responses are used.
- Without credentials, DevAgent falls back to keyword retrieval and deterministic
  summaries so demos remain usable offline.
- Controlled edits always show a diff and require explicit confirmation before
  applying changes.
- The current MVP uses a lightweight JSON index, so installs stay fast and do
  not require a local vector database.

## Local Testing Guide

Activate the virtual environment:

```powershell
.\.venv\Scripts\activate
```

Confirm the CLI is installed:

```powershell
devagent --help
```

Run the automated tests:

```powershell
python -m pytest
```

Bind this repo as your first workspace:

```powershell
devagent workspace bind .
devagent workspace status
```

Build the local code index:

```powershell
devagent index
```

Test repo-aware chat without Gemini:

```powershell
devagent chat "Explain the project structure"
```

Then test with Gemini:

```powershell
copy .env.example .env
notepad .env
```

Set `GEMINI_API_KEY`, then run:

```powershell
devagent index
devagent chat "Where is the CLI implemented?"
```

Test Git and inspection helpers:

```powershell
devagent git status
devagent commit suggest
devagent inspect
```

Inspect Node dependencies directly:

```powershell
devagent packages
```

On Windows `cmd.exe`, use `type package.json` instead of Unix `cat package.json`.
In PowerShell, use `Get-Content package.json`.

Test controlled edit mode:

```powershell
devagent edit "Add a short comment above the workspace bind command"
```

DevAgent will show a diff and ask before applying it.

## Git Assistant

Run this first to see the Git actions in plain language:

```powershell
devagent git
```

In a normal terminal, this opens an interactive selector with arrow-key navigation.
If arrow-mode is unavailable, DevAgent falls back to a simple numbered menu.

DevAgent now supports:

```powershell
devagent git status
devagent git add
devagent git add client/package.json
devagent git branch create feature/login
devagent git branch switch main
devagent git commit
devagent git pull
devagent git push
devagent git pr preview
devagent git pr create
devagent git merge conflicts
devagent git merge abort
devagent git merge continue
```

`devagent git commit` stages all changes by default and auto-generates a commit
message unless you pass `--message`.

## Guided Project Setup

For a user-friendly first run, use:

```powershell
devagent new project
```

DevAgent asks whether you already have a GitHub repo or have a local copy to publish.

If you choose GitHub, it asks for the normal GitHub repo page URL, lets you choose
where on your PC to clone it, converts the URL to the clone URL, clones the repo,
binds the workspace, detects the project type, and can offer dependency install or
opening VS Code.

Dependency install checks the repo root and nested app folders such as
`client/package.json` and `server/package.json`, then runs the right install
command in each folder. For Python apps, DevAgent creates a local `.venv`
inside that app folder first and installs into that virtual environment instead
of the global Python interpreter.

If you choose local, it lets you choose the local project folder, creates a GitHub
repo using `gh`, adds `origin`, commits if needed, pushes, and binds the workspace.

## Runtime Agent

DevAgent can now act more like a local teammate by launching your workspace
services for you instead of only describing what to run.

Use:

```powershell
devagent run
```

That shows:

- auto-detected launch targets such as `frontend> npm run dev`
- Python app targets such as `backend> python main.py`
- saved launch phrases for your workspace

To launch the detected stack in separate terminals:

```powershell
devagent run start
```

To launch the stack and open the detected local app in your browser:

```powershell
devagent run start --open-browser
```

On Windows, Python services open in a new `cmd.exe` terminal with the local
`.venv` activated automatically. If the `.venv` does not exist yet but the app
has `requirements.txt` or `pyproject.toml`, DevAgent bootstraps that `.venv`
before starting the service.

To remember a startup phrase for the whole detected stack:

```powershell
devagent run save "I order you to start in the name of jesus"
devagent run start "I order you to start in the name of jesus" --open-browser
```

To remember a custom one-off command:

```powershell
devagent run save "wake the frontend" --command "npm run dev" --cwd frontend
devagent run start "wake the frontend"
```

These phrases are stored in DevAgent's workspace cache, not in your project's
`package.json`, so the app's own scripts stay clean while DevAgent still feels
agentic and personal.
