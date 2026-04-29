# DevAgent CLI Guide

This guide explains the current DevAgent CLI command surface with examples.
It is based on the live command definitions in
`devagent/cli/main.py`.

Related docs:

- [README.md](README.md) for installation, onboarding, and feature overview
- [SHELL_GUIDE.md](SHELL_GUIDE.md) for the interactive shell surface

## What DevAgent does

DevAgent is a local-first developer assistant for:

- binding to a workspace
- indexing code for repo-aware chat
- generating controlled code edits
- helping with Git workflows
- launching local apps
- inspecting project health
- selecting AI providers and models

## Quick mental model

Most commands work against the **currently bound workspace**.

A typical first-run flow looks like this:

```cmd
devagent workspace bind "D:\Projects\MyApp"
devagent workspace status
devagent ai status
devagent index
devagent chat "Explain this project"
```

If you run:

```cmd
devagent
```

in an interactive terminal, DevAgent opens the **agent shell** instead of
printing help.

## Top-level command families

DevAgent currently exposes these command families:

- `ai`
- `workspace`
- `setup`
- `new`
- `chat`
- `run`
- `git`
- `commit`
- `edit`
- `index`
- `packages`
- `inspect`
- `watch`
- alias commands: `clone`, `publish`

## 1. General entry points

### `devagent`

Opens the interactive shell when a workspace is already bound.

Example:

```cmd
devagent
```

### `devagent --help`

Shows the top-level CLI catalog.

Example:

```cmd
devagent --help
```

## 2. AI commands

Use these to inspect configured providers and choose saved defaults.

DevAgent currently supports:

- Gemini
- xAI

### `devagent ai`

Shows current AI status.

Example:

```cmd
devagent ai
```

### `devagent ai status`

Shows:

- configured providers
- selected provider
- active chat model
- active deep model
- active embedding model

Examples:

```cmd
devagent ai status
devagent ai status --refresh
```

### `devagent ai models`

Lists visible models for the configured providers.

Examples:

```cmd
devagent ai models
devagent ai models --provider gemini
devagent ai models --provider xai --refresh
```

### `devagent ai use`

Saves the default provider and model selection DevAgent should use for chat,
edit, and related AI-backed features.

Examples:

```cmd
devagent ai use --provider gemini
devagent ai use --provider gemini --model gemini-2.5-flash --deep-model gemini-2.5-pro --embedding-model gemini-embedding-001
devagent ai use --provider xai --model grok-3-mini --deep-model grok-3-mini
```

### `devagent ai reset`

Clears saved AI preferences and falls back to environment-driven defaults.

Example:

```cmd
devagent ai reset
```

## 3. Workspace commands

### `devagent workspace bind <path>`

Binds DevAgent to a project folder.

Examples:

```cmd
devagent workspace bind "D:\Vs code Projects\Rock-Paper-Scissor"
devagent workspace bind .
```

### `devagent workspace status`

Shows the active workspace snapshot, including project type, branch, dirty
state, and changed files.

Example:

```cmd
devagent workspace status
```

## 4. Setup and onboarding commands

### `devagent setup clone <repo-url>`

Clones a GitHub repo and can optionally install dependencies and open VS Code.

Examples:

```cmd
devagent setup clone https://github.com/Aritrajit-Guha/DevAgent-CLI
devagent setup clone https://github.com/Aritrajit-Guha/DevAgent-CLI --target "D:\Projects"
devagent setup clone https://github.com/Aritrajit-Guha/DevAgent-CLI --target "D:\Projects" --install-deps --open-code
```

### `devagent clone <repo-url>`

Alias for `devagent setup clone`.

Example:

```cmd
devagent clone https://github.com/Aritrajit-Guha/DevAgent-CLI --target "D:\Projects"
```

### `devagent setup publish <path>`

Publishes a local project to GitHub.

Examples:

```cmd
devagent setup publish "D:\Projects\MyApp"
devagent setup publish "D:\Projects\MyApp" --name myapp
devagent setup publish "D:\Projects\MyApp" --name myapp --private
devagent setup publish "D:\Projects\MyApp" --name myapp --no-push
```

### `devagent publish <path>`

Alias for `devagent setup publish`.

Example:

```cmd
devagent publish "D:\Projects\MyApp" --name myapp
```

### `devagent new project`

Guided onboarding flow for either:

- cloning an existing GitHub repo
- publishing a local project

Examples:

```cmd
devagent new project
devagent new project --start "D:\Projects"
```

## 5. Repo understanding commands

### `devagent index`

Builds or refreshes the local code index used by chat and edit workflows.

Examples:

```cmd
devagent index
devagent index --path "D:\Projects\AnotherApp"
```

### `devagent chat "<question>"`

Asks a repo-aware question about the active workspace.

Examples:

```cmd
devagent chat "Explain the project structure"
devagent chat "Where is authentication implemented?"
devagent chat "Explain the backend architecture" --deep
devagent chat "Explain this repo from scratch" --new-session
```

### `devagent packages`

Lists direct Node dependencies from `package.json` files in the bound
workspace.

Example:

```cmd
devagent packages
```

### `devagent inspect`

Runs DevAgent's lightweight safety and repo-hygiene checks.

Example:

```cmd
devagent inspect
```

### `devagent watch`

Watches the active workspace for file changes.

Examples:

```cmd
devagent watch
devagent watch --interval 2.0
```

## 6. Run commands

Use these to launch local apps and save reusable natural-language launch
phrases.

### `devagent run`

Shows detected run targets and saved run phrases.

Example:

```cmd
devagent run
```

### `devagent run start`

Starts the detected stack, or starts a saved phrase if one is provided.

Examples:

```cmd
devagent run start
devagent run start --open-browser
devagent run start --no-open-browser
devagent run start "Start the app"
```

### `devagent run save "<phrase>"`

Saves either:

- the detected stack
- a custom manual command

Examples:

```cmd
devagent run save "Start the app" --open-browser
devagent run save "Start backend only" --command "python app.py" --cwd backend
devagent run save "Launch frontend" --command "npm run dev" --cwd frontend --description "Vite dev server"
```

### `devagent run list`

Lists detected run targets and saved phrases.

Example:

```cmd
devagent run list
```

### `devagent run forget "<phrase>"`

Deletes a saved run phrase.

Example:

```cmd
devagent run forget "Start the app"
```

## 7. Edit command

### `devagent edit "<instruction>"`

Describes a code change in plain English, shows the proposed diff, and then
asks before applying it.

Examples:

```cmd
devagent edit "Add a thank you line at the end of README.md"
devagent edit "Add a light and dark theme toggle button"
devagent edit "Fix the heading text in index.html"
```

### `devagent edit "<instruction>" --yes`

Applies the proposed diff without a confirmation prompt.

Example:

```cmd
devagent edit "Add a short note to README.md" --yes
```

## 8. Git commands

### `devagent git`

In an interactive terminal, opens the guided Git menu. If interactive menu mode
is unavailable, DevAgent prints a Git command catalog.

Example:

```cmd
devagent git
```

### `devagent git status`

Shows the current branch and working-tree state.

Example:

```cmd
devagent git status
```

### `devagent git add [path]`

Stages the whole workspace or a specific path.

Examples:

```cmd
devagent git add
devagent git add README.md
devagent git add frontend
```

### `devagent git branch create <name>`

Creates a new branch and switches to it.

Examples:

```cmd
devagent git branch create feature/theme-toggle
devagent git branch create bugfix/login-flow
```

### `devagent git branch switch <name>`

Switches to an existing branch.

Examples:

```cmd
devagent git branch switch main
devagent git branch switch develop
devagent git branch switch bugfix/login-flow --force
```

### `devagent git commit`

Creates a commit. If you do not pass `-m`, DevAgent auto-generates a commit
message from the actual diff.

Examples:

```cmd
devagent git commit
devagent git commit -m "fix: correct landing page heading"
devagent git commit --staged-only
```

### `devagent git pull`

Pulls the latest changes into the current branch. DevAgent prefers the tracked
upstream and only uses overrides when needed.

Examples:

```cmd
devagent git pull
devagent git pull --remote origin --branch main
```

### `devagent git push`

Pushes the current branch to GitHub. DevAgent prefers the tracked branch and
uses overrides only when needed.

Examples:

```cmd
devagent git push
devagent git push --remote origin
devagent git push --remote origin --branch feature/theme-toggle
```

### `devagent git pr preview`

Previews the PR title and body for the current branch.

Examples:

```cmd
devagent git pr preview
devagent git pr preview --base main
devagent git pr preview --base develop --draft
```

### `devagent git pr create`

Creates a pull request for the current branch.

Examples:

```cmd
devagent git pr create
devagent git pr create --base main
devagent git pr create --base develop --draft
devagent git pr create --title "Add theme toggle" --body "Adds a simple UI theme switcher."
```

### `devagent git merge conflicts`

Shows merge conflict files and details.

Example:

```cmd
devagent git merge conflicts
```

### `devagent git merge abort`

Aborts the current merge.

Example:

```cmd
devagent git merge abort
```

### `devagent git merge continue`

Continues the merge after conflicts are resolved.

Example:

```cmd
devagent git merge continue
```

## 9. Commit helper

### `devagent commit suggest`

Previews a context-driven commit subject and body without creating a commit.

Examples:

```cmd
devagent commit suggest
devagent commit suggest --plain
```

## 10. Common real-world flows

### Bind a project and understand it

```cmd
devagent workspace bind "D:\Vs code Projects\Rock-Paper-Scissor"
devagent workspace status
devagent ai status
devagent index
devagent chat "Explain this project"
```

### Start an app and save a phrase for later

```cmd
devagent run start --open-browser
devagent run save "Start the app" --open-browser
```

Later:

```cmd
devagent run start "Start the app"
```

### Make a code change and commit it

```cmd
devagent edit "Add a thank you line at the end of README.md"
devagent git add
devagent commit suggest
devagent git commit
```

### Push and open a PR

```cmd
devagent git push
devagent git pr preview
devagent git pr create
```

## 11. Common gotchas

- There is **no** `devagent status` command.
  Use:

  ```cmd
  devagent workspace status
  ```

- Most commands expect a bound workspace first:

  ```cmd
  devagent workspace bind "D:\Projects\MyApp"
  ```

- `devagent git` and `devagent run` behave like guided entry points. They are
  not the same kind of command as `devagent git status` or `devagent run start`.

- `devagent ai` can work even if no workspace is currently bound, because AI
  settings are global to DevAgent.

## 12. Best next commands to remember

If you only memorize a few commands, make it these:

```cmd
devagent workspace bind "D:\Projects\MyApp"
devagent workspace status
devagent ai status
devagent index
devagent chat "Explain this repo"
devagent edit "Describe the change you want"
devagent git status
devagent git commit
devagent git push
devagent git pr create
```

If you prefer prompts and menus over explicit commands, open the interactive
shell instead:

```cmd
devagent
```
