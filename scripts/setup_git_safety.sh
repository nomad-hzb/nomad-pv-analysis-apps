#!/bin/sh
# Run once per clone (e.g. once in the NOMAD upload's Jupyter terminal) to make
# `git pull` always leave Learning/ in its canonical, committed state:
#
#   - core.hooksPath -> scripts/git-hooks, so the tracked post-merge hook there
#     resets Learning/ after every merge (works no matter how the merge was
#     triggered -- `git pull`, a GUI, JupyterLab's git extension, ...). This
#     alone is enough when the incoming change doesn't touch a file you've
#     locally edited.
#   - a `git` shell function (sourced from your shell profile) that resets
#     Learning/ *before* `git pull` runs too, so a local edit can never make
#     the pull itself fail with "local changes would be overwritten by
#     merge". This can't be a git alias -- git refuses to let an alias shadow
#     an existing command name like "pull" -- so it has to live in the shell.
#
# After running this, `git pull` behaves exactly as before from the outside --
# nothing new to type or remember.
set -e
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

git config core.hooksPath scripts/git-hooks

PROFILE="$HOME/.bashrc"
MARKER="# nomad_voila: keep Learning/ pristine on git pull"
SOURCE_LINE=". \"$REPO_ROOT/scripts/git-pull-safe.sh\""

if [ -f "$PROFILE" ] && grep -qF "$MARKER" "$PROFILE"; then
    echo "Shell wrapper already installed in $PROFILE, skipping."
else
    {
        echo ""
        echo "$MARKER"
        echo "$SOURCE_LINE"
    } >> "$PROFILE"
    echo "Added the git-pull wrapper to $PROFILE (restart your terminal, or run: $SOURCE_LINE)"
fi

echo "Done. 'git pull' now resets Learning/ before and after every pull."
