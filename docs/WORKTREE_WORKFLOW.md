# Worktree Workflow

## The problem this solves

A single git clone has exactly one branch checked out at a time. If you
run two Claude Code sessions against the same clone — say, one adding a
metric to the registry while another builds a new Slack bot filter — they
share one working directory. Whichever session switches branches (or
whichever tool auto-stashes) can stomp on the other session's uncommitted
files. This isn't an "analysts colliding with each other" problem — two
different people already don't collide, since they'd naturally work on
separate clones or branches. It's a **within one analyst, running several
Claude sessions in parallel** problem: you want to build three things at
once without three full re-clones and without them corrupting each
other's state.

`git worktree` solves exactly this: multiple working directories, each
with its own branch checked out, all sharing one `.git` object store —
so you're not re-cloning gigabytes of history three times, but each
session still gets a fully isolated file tree.

## Setup

From a normal clone of this repo:

```bash
git clone <repo-url> bi-framework
cd bi-framework
```

Create an isolated worktree per parallel task, each on its own branch:

```bash
git worktree add ../bi-framework-new-metric   -b analyst/add-ltv-180d
git worktree add ../bi-framework-slack-filter -b analyst/slack-region-filter
git worktree add ../bi-framework-bugfix       -b analyst/fix-churn-window
```

You now have three sibling directories, each a full working copy on its
own branch, sharing one `.git`:

```
bi-framework/               <- original clone, e.g. still on main
bi-framework-new-metric/    <- branch: analyst/add-ltv-180d
bi-framework-slack-filter/  <- branch: analyst/slack-region-filter
bi-framework-bugfix/        <- branch: analyst/fix-churn-window
```

Point a separate Claude Code session at each directory. They can run
`pytest`, regenerate the synthetic warehouse, and edit files entirely
independently — no branch-switching race, no stash conflicts.

## Cleaning up

```bash
git worktree remove ../bi-framework-new-metric
git worktree list   # confirm what's still checked out
```

Removing a worktree doesn't delete its branch — merge or delete that
separately once the PR lands.

## The knowledge-sharing loop this enables

The reason this matters beyond convenience: each worktree is a normal
branch/PR, so when a session in `bi-framework-bugfix` finds and fixes a
real issue (say, `churn_rate_90d`'s window was off by a day), that fix
goes through the same registry + verification-test + CI path as any other
change, and merges back to `main` where every other worktree — and every
other analyst's next `git pull` — picks it up. Parallel sessions don't
fork knowledge; they all feed the same registry.

## When you don't need this

If you're one analyst doing one thing at a time, a normal branch on a
single clone is simpler and this adds nothing. Reach for worktrees when
you're specifically running multiple Claude Code sessions concurrently
against the same repo and want them isolated without paying for multiple
full clones.
