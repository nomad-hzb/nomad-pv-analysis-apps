# Deploying the app suite to a second NOMAD Oasis

This repo defaults to the HZB SE Oasis (`nomad-hzb-se.de`) but contains no
hardcoded dependency on it. Everything a second deployment needs to change
lives in one gitignored file, `oasis_local_config.py`, read by `bootstrap.py`
at the top of every notebook.

The worked example throughout is the CE-AME Oasis
(`https://nomad-ce-ame.helmholtz-berlin.de/`), which needs two things HZB does
not: a different host, and an outbound HTTP proxy.

---

## 1. Check the target Oasis is compatible

The apps assume a NOMAD Oasis running the `nomad_hysprint` schema package and
offering the `voila` NORTH tool. Confirm both before uploading anything:

```bash
curl -s https://<your-oasis>/nomad-oasis/api/v1/info | python -m json.tool
```

Look for:

| Field | Expected | Why it matters |
|---|---|---|
| `version` | 1.4.x, `oasis: true` | API shape the apps are written against |
| `plugin_packages` / schema | `nomad_hysprint.schema_packages:hysprint_package` | `ENTRY_TYPES` in `shared/hysprint_utils/config.py` names `HySprint_*` entry types; a different schema means those queries return nothing |
| `north_tools` | includes `voila` | how the apps are launched |

CE-AME was probed and returns NOMAD 1.4.2, the `hysprint_package` schema, and
both `voila` and `jupyter2`, so no schema work is needed. If your Oasis runs a
different schema package, `ENTRY_TYPES` is the single place to remap the names.

Also note the API base path. CE-AME serves at `/nomad-oasis` like HZB; if yours
differs, see the known gap on path literals at the end of this document.

## 2. Upload the repo

Either drag the repo in as a NOMAD upload, or clone it from a NORTH terminal.
Cloning is usually easier to update later, but on a proxied Oasis it needs the
proxy set up first - see 2a.

Whichever route you take, preserve the directory structure. The layout matters
more than the name: every notebook's cell 0 is

```python
import runpy
_ = runpy.run_path("../../bootstrap.py")
```

which resolves from `apps/<AppName>/` to the repo root. As long as `apps/`,
`shared/` and `bootstrap.py` keep their relative positions, the upload's own
`<slug>-<hash>` folder name is irrelevant - that is the whole point of the
bootstrap, and why no path in this repo names a specific upload any more.

To clone it, from a NORTH Jupyter terminal (`jupyter2` tool, File > New >
Terminal), in the uploads directory you want it to live in:

```bash
git clone https://github.com/nomad-hzb/nomad-pv-analysis-apps.git
```

On a proxied Oasis that fails before it starts:

```
fatal: unable to access 'https://github.com/nomad-hzb/nomad-pv-analysis-apps.git/':
Failed to connect to github.com port 443 after 4 ms: Couldn't connect to server
```

## 2a. Proxy for the terminal (proxied Oasis only)

`oasis_local_config.py` cannot help here, and not by oversight: it is applied
by `bootstrap.py`, which runs inside a *kernel*, and which lives inside the
repo you are trying to clone. The clone happens in a plain shell before either
exists, so the proxy has to be exported in that shell.

One variable is enough for the clone, verified on CE-AME:

```bash
export HTTPS_PROXY=http://proxy.example.org:3128
git clone https://github.com/nomad-hzb/nomad-pv-analysis-apps.git
```

`git`'s HTTP layer is libcurl, which reads `HTTPS_PROXY` for an `https://`
remote - and GitHub is external, so no `NO_PROXY` entry applies to it.

For anything else you do from that terminal (`pip install`, `curl`), add the
rest. libcurl reads only the *lowercase* `http_proxy` for plain HTTP, so the
uppercase-only form is not enough in general:

```bash
export HTTP_PROXY=http://proxy.example.org:3128
export NO_PROXY=localhost,127.0.0.1
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export no_proxy=$NO_PROXY
```

Keep `NO_PROXY` to loopback unless you have checked otherwise. Excluding the
Oasis host looks right - it is in-house, so why proxy it - but a container that
needs a proxy at all usually has no direct route to anything: CE-AME answers a
direct call to its own Oasis with `No route to host`.

If a clone still fails, check the proxy is reachable at all before varying the
value:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' https://github.com
```

`200` means the proxy works. A hang or `000` means the proxy host or port is
wrong for this deployment - ask whoever administers the Oasis rather than
varying the value.

These exports last only for that terminal session. Two ways to persist them,
both subject to whether your NORTH container keeps `/home/jovyan` between
sessions - on many deployments it does not, and re-exporting per session is
simply the normal workflow:

```bash
# option 1: every new shell in this container
cat >> ~/.bashrc <<'EOF'
  export HTTP_PROXY=http://proxy.example.org:3128
export HTTPS_PROXY=http://proxy.example.org:3128
export NO_PROXY=localhost,127.0.0.1
export http_proxy=$HTTP_PROXY
export https_proxy=$HTTPS_PROXY
export no_proxy=$NO_PROXY
EOF

# option 2: git only, written to ~/.gitconfig
git config --global http.proxy http://proxy.example.org:3128
git config --global https.proxy http://proxy.example.org:3128
```

Option 2 covers `git` alone. Option 1 also covers `pip` and `curl`, which you
will want for any manual install from that terminal.

Note this proxy setup is for the *terminal* only. It does not carry into the
Voila kernel that actually runs the apps - a kernel is a separate process
started by NORTH, not a child of your shell. That is exactly what
`oasis_local_config.py` and step 3 are for, and why the same values appear in
both places.

## 3. Create `oasis_local_config.py`

Create it at the repo root of the upload, next to `bootstrap.py`. It is
gitignored (same pattern as `secrets.py`) because it describes one deployment,
not the repo - it travels with the upload, and is not committed upstream.

Every uppercase string assignment in it is exported as an environment variable
of the same name before `hysprint_utils` is imported or installed. Anything
already set at the container level wins; this file never overwrites it.

### The CE-AME file

The proxy host below is a placeholder. Deployment-specific values like the
real proxy address are deliberately not written into this repo - they belong
in the gitignored `oasis_local_config.py` of that one deployment. Get the
actual address from whoever administers the Oasis.

```python
# --- Which Oasis the apps talk to ---
HYSPRINT_URL_BASE = "https://nomad-ce-ame.helmholtz-berlin.de"
HYSPRINT_API_ENDPOINT = "/nomad-oasis/api/v1"

# --- Outbound network ---
HTTP_PROXY = "http://proxy.example.org:3128"
HTTPS_PROXY = "http://proxy.example.org:3128"
NO_PROXY = "localhost,127.0.0.1"
```

### What each variable does

| Variable | Needed when | Notes |
|---|---|---|
| `HYSPRINT_URL_BASE` | always, on any non-HZB Oasis | Read by `shared/hysprint_utils/config.py`. No trailing slash. This is the one variable you cannot skip. |
| `HYSPRINT_API_ENDPOINT` | only if the API is not at `/nomad-oasis/api/v1` | Identical to the HZB default on CE-AME. Set anyway so the deployment is fully described by one file. |
| `HTTP_PROXY`, `HTTPS_PROXY` | the container has no direct outbound route | Applied *before* `pip install shared/` runs, because pip fetches `hatchling` from PyPI to build it. Also picked up by `git` for the `insitu_analyser` dependency. |
| `NO_PROXY` | whenever a proxy is set | Hosts that must be reached *without* the proxy. Defaults to `localhost,127.0.0.1` if omitted. Do not add the Oasis host unless a direct call to it actually works from the container - on CE-AME it does not, and excluding it breaks every API call with `Errno 113 No route to host`. |

### Ordering, and why it is not cosmetic

`bootstrap.py` applies the environment, then applies the proxy, then installs
`shared/`. Both halves of that order are load-bearing:

- `hysprint_utils.config` reads `HYSPRINT_URL_BASE` **at import time**, so
  setting it after any app import has no effect.
- `pip install <local dir>` is not an offline operation - it builds in an
  isolated environment and fetches `hatchling` from PyPI. On a proxied Oasis,
  a bootstrap that installs before setting the proxy fails outright.

## 4. Launch and verify

Launch the `voila` NORTH tool against `apps/App_dashboard/app_dashboard.ipynb`
first - it exercises auth, the API, and the NORTH URL construction all at once.

Run this in a fresh kernel on the target Oasis to confirm the environment
before debugging anything else:

```python
import runpy
_ = runpy.run_path("../../bootstrap.py")

import os
from hysprint_utils.config import API_ENDPOINT, URL_BASE

print("URL_BASE    :", URL_BASE)
print("API_ENDPOINT:", API_ENDPOINT)
print("proxy       :", os.environ.get("HTTPS_PROXY"))
print("no_proxy    :", os.environ.get("NO_PROXY"))

import requests
print("info        :", requests.get(f"{URL_BASE}{API_ENDPOINT}/info", timeout=30).status_code)
```

Expected on CE-AME: the URL and proxy values from the config file, and `200`
from the `/info` call. That `200` is the single most useful result here - it
proves the URL, the proxy and `NO_PROXY` are all correct together, since the
call has to reach the Oasis through the proxy.

Checklist for the dashboard itself:

- [ ] Dashboard renders with your username in the header
- [ ] App cards point at `https://<your-oasis>/nomad-oasis/north/...`
- [ ] Clicking a card opens that app's Voila instance
- [ ] That app can authenticate and list batches from your Oasis

## 5. Known gaps on a non-HZB Oasis

These are tracked, not silently broken. None of them block the core apps.

**The "Projects" section of the App Dashboard will 404.** Its six cards
deep-link into specific HZB uploads (the slot-die-coater ML pipeline) that do
not exist elsewhere. Each card's upload ID is overridable via a
`HYSPRINT_PROJECT_*_UPLOAD_ID` variable, and setting one to an empty string
drops that card - setting all six drops the section entirely. Deliberately not
configured for CE-AME yet; see `apps/App_dashboard/data_manager.py`.

**The nine `Electrochemical_analysis` notebooks have no bootstrap cell.** They
fall back to the HZB URL and get no proxy, so they will not work on a second
Oasis. They are pre-existing raw notebooks (`!pip install impedance` in cell 0,
star imports) that have not been through the unification pass.

**`ISA_Previewer` needs outbound git access.** It pins `insitu_analyser` from
`codebase.helmholtz.cloud`, installed by `bootstrap.py` with the rest of that
app's dependencies (section 8). The clone runs through `git`, which reads
`HTTPS_PROXY` from the environment and inherits it from pip's subprocess.
Verified on CE-AME: that host is reachable through the proxy, so no extra
routing is needed. If the app ever reports `ModuleNotFoundError: No module
named 'insitu_analyser'`, install it by hand in a NORTH terminal to see the
real error:

```bash
export HTTPS_PROXY=http://proxy.example.org:3128
pip install "insitu_analyser @ git+https://codebase.helmholtz.cloud/hzb-se-alm/insitu_analyser.git@v0.1.52"
```

**Some `/nomad-oasis/...` path literals bypass `API_ENDPOINT`.** GUI-link and
NORTH-path templates in `auth_manager.py`, `App_dashboard/data_manager.py`,
`Global_analyzer/utils.py`, `ISA_Previewer/config.py` and `JV-Analysis/app.py`
build their own prefixes. Harmless wherever the base path is `/nomad-oasis`
(HZB and CE-AME both), broken on an Oasis served under a different prefix.

## 6. Local development

Unrelated to Oasis deployment, but the same variables apply. Export them in
your shell instead of using `oasis_local_config.py`:

```bash
export HYSPRINT_URL_BASE=https://your-oasis.example.org
export HYSPRINT_API_ENDPOINT=/nomad-oasis/api/v1
```

See `README.md` for the local install and how to supply an access token.

## 7. Git cheat sheet for the NORTH terminal

Everything here assumes `HTTPS_PROXY` is exported first on a proxied Oasis
(section 2a) - anything touching the network fails without it.

### Get the repo and pick a branch

```bash
git clone https://github.com/nomad-hzb/nomad-pv-analysis-apps.git
cd nomad-pv-analysis-apps

git branch -a                    # every branch, including remote ones
git checkout <branch-name>       # switch; a fresh clone needs no fetch first
git branch --show-current        # confirm where you are
```

If `checkout` says `pathspec ... did not match`, your clone predates the
branch. `git fetch origin`, then retry.

### Stay up to date

```bash
git pull                         # tracking is set up by checkout, no args needed
git log --oneline -5             # what you have
git fetch origin && git status   # see if you are behind without changing anything
```

### Notebook outputs, the usual reason a checkout is refused

Running a notebook in the `jupyter2` tool writes its output cells back into
the `.ipynb`, so git reports it as modified and refuses to switch branches.
Those outputs are exhaust - discard them:

```bash
git status                       # always look before discarding
git restore <notebook>.ipynb     # one file
git restore .                    # every modified tracked file
```

`git restore` does not touch untracked or ignored files, so
`oasis_local_config.py` is never at risk. It is irreversible for the files it
does touch, hence checking `git status` first.

Use `git stash` only for changes you actually want back:

```bash
git stash                        # shelve, giving a clean tree
git stash pop                    # take them back
git stash list                   # what is shelved
```

Stashing run-output noise is the wrong tool: `pop` would just replay it onto
the other branch, possibly as a conflict.

### What never needs protecting

`oasis_local_config.py` and `secrets.py` are gitignored. They survive
`checkout`, `pull`, `restore` and `stash` untouched - create them once on the
Oasis and they stay put across every branch switch.

## 8. How dependencies get installed

Nothing on the Oasis runs `pip install` by hand. `bootstrap.py` does all of it
from cell 0, in this order:

1. **`shared/`** - the `hysprint_utils` library every app imports. A failure
   here is fatal and raises, because no app works without it.
2. **The app's own directory**, when it has a `pyproject.toml`. The cwd is the
   notebook's own folder, so this installs exactly the app being launched,
   along with everything in its `dependencies` list.

Step 2 is why `apps/<App>/pyproject.toml` is worth keeping accurate: it is the
only thing that installs an app's third-party requirements. Before it existed,
those lists were inert at runtime - which is how `ISA_Previewer` came to fail
with `ModuleNotFoundError: No module named 'insitu_analyser'` on a fresh
CE-AME container while the pin sat in its dependency list all along.

**It runs once per container, not once per launch.** On success bootstrap
writes a marker into the temp directory, keyed on the app's path and the
contents of its `pyproject.toml`. Later launches of the same app skip the
install entirely; editing the dependency list changes the key, so the next
launch reinstalls. Nothing needs clearing by hand.

**A failed app install is a warning, not an error.** Most apps need nothing
beyond what the NORTH image already provides, and none of them were installed
at all until now - so pip failing here (no network, an unreachable git host)
must not take down an app that would otherwise run fine. The warning names the
app and carries pip's output. Only the `shared/` install is fatal.

The practical consequence for a proxied Oasis: app launches reach the network,
so the proxy in `oasis_local_config.py` has to be right before any app with
third-party dependencies will start cleanly on a fresh container.

### Import-time banners

Bootstrap also stops libraries printing into the app's UI while they are being
imported. INSIGHT, pulled in by `insitu_analyser`, greets stdout with a
multi-line welcome banner (version, licence status, plot style, backend); under
Voila that appears above the app itself and reads as an error to anyone who
does not recognise it.

Since cell 0 has finished by the time an app's imports run, bootstrap leaves a
hook behind rather than wrapping anything: `builtins.__import__` redirects
stdout for the duration of each outermost import, for the rest of that kernel's
life. It is deliberately narrow - stderr is untouched so warnings still
surface, runtime output is untouched, already-imported modules take a fast
path, and the suppressed text is logged at debug rather than discarded.

If you are debugging an import and want that output back:

```python
import os
os.environ["HYSPRINT_KEEP_IMPORT_OUTPUT"] = "1"   # before cell 0 runs
```
