#!/bin/sh
# Sourced from your shell profile by scripts/setup_git_safety.sh.
#
# Wraps `git` so that typing the literal command `git pull` resets Learning/
# to HEAD first. This can't be done as a git alias -- git refuses to let an
# alias shadow an existing command name like "pull" -- so it has to happen
# at the shell level instead. Every other `git ...` command passes straight
# through unchanged.
git() {
    if [ "$1" = "pull" ]; then
        # ':/Learning/' is relative to the repo root, not the current directory,
        # so this works the same whether you're at the repo root or in apps/SomeApp/.
        command git checkout HEAD -- ':/Learning/' 2>/dev/null
    fi
    command git "$@"
}
