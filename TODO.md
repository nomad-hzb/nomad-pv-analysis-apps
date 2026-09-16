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