# Known TODOs

Open items that are not yet GitHub issues. Once one is filed on
[nomad-hzb/nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues),
the issue becomes the source of truth and the entry here should be deleted.

## Excel_creator: hardcoded links in the generated workbook

`apps/Excel_creator/sheet_data_entry_guide.py:213` writes a hyperlink to
`https://nomad-hzb-se.de/nomad-oasis/gui/search/voila` into every generated
Excel file, and line 224 links to an HZB-specific `scribehow.com` how-to guide.

Both name the HZB SE Oasis by hand, so on another deployment they point at an
Oasis the user is not working on. Unlike the other apps this was not simply
derived from `hysprint_utils.config`, because the decision comes first: the link
leaves the app inside a file that gets mailed around, and it targets a Voila GUI
page rather than the API. Should a generated workbook name the deployment that
produced it, or always point at SE?

The GitHub links on the citation sheet
(`apps/Excel_creator/sheet_how_to_cite.py:7,16,22,28`) may want revisiting in
the same pass: they point at the `nomad-hzb/nomad-hysprint` schema repo, which
may no longer be the right thing to cite now that the apps are versioned and
released separately from it.

Needs an `Excel_creator` version bump when done.

## Open question: how should Oasis-specific apps and content be handled?

The repo runs on more than one NOMAD Oasis, but some apps, sections and links
are not portable: they are tied to data, uploads or documentation that exist on
exactly one deployment. There is currently no general rule for these, and three
different ad-hoc answers are already in the tree:

- **Per-item env override with an opt-out.** App Dashboard's Projects cards
  deep-link into specific HZB uploads. Each card's upload ID reads from a
  `HYSPRINT_PROJECT_*_UPLOAD_ID` variable, and setting one to an empty string
  drops that card, all six drop the section
  (`apps/App_dashboard/data_manager.py:301`). Flexible, but every new item
  needs its own variable and nobody discovers them without reading
  `DEPLOYMENT.md`.
- **Deliberately hardcoded.** `apps/PeroDatabase_downloader/config.py` pins the
  SE Oasis as a fixed data source to download *from*, on every deployment, the
  same way it pins the public central server.
- **Derived from config.** Most apps build every URL from
  `hysprint_utils.config`, so they simply follow the deployment.

Open questions, in rough order of how much they decide:

1. Is "Oasis-specific" a property of a whole **app**, or only of individual
   links and sections inside otherwise-portable apps? Today it is only the
   latter, but an app whose data lives on one Oasis is plausible.
2. Should a non-portable item be **hidden** on other deployments (the Projects
   approach), **shown but labelled** as belonging to another Oasis, or **left
   pointing at its home Oasis** on the grounds that the link still works for
   whoever has access?
3. Should the App Dashboard know which deployment it is on, so this is one
   declaration per app rather than a growing set of env variables?
4. Does the eventual NOMAD plugin packaging (see `CLAUDE.md`, "Ultimate goal")
   change the answer? If apps ship as NORTH tool entry points, per-deployment
   content may belong in the tool configuration rather than in the app.

No decision yet, and no work should start from this entry - it exists so the
next person hitting the problem finds the prior art instead of inventing a
fourth mechanism.