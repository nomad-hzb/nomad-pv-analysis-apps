# App Dashboard: user manual

## What the app is for

The starting page for all the analysis apps (NOMAD Analysis Tools). It shows one card per app,
grouped by topic, and opens the app you click in a new browser tab, in your own NOMAD session.
It does not read or change any data.

## How to use it

1. **Open the dashboard from your NOMAD upload page.** The line under the title says who you are
   signed in as. If it says the username could not be detected, the links may not work: reopen
   the dashboard from your NOMAD upload page. An app card then shows a message instead of
   opening a tab.
2. **Click a card** to open that app in a new tab. If a link ends in a "404", refresh the dashboard
   from the NOMAD upload page, so that it picks up your current username and upload.
3. **Groups.** Each group has a header; click it to close or open the group. The groups are:
   - *Data Management*: File Uploader, Excel Creator, Smart Databaser, Entry Auditor, Database
     Downloader.
   - *Device Characterization*: JV Analysis, EQE Analyzer, MPPT Analyzer, AbsPL Analysis, TRPL
     Analysis, XRD Peak Finder, NMR Analysis, Peak Explorer.
   - *In-situ and GIWAXS Data Analysis*: ISA Previewer, GIWAXS Analysis, Optical Analysis, Timely
     Teller, Thickness Tracer (not implemented yet).
   - *Utilities & Calculators*: Design of Experiments, Global Analyzer, Hansen Calculator, Wetting
     Envelope, Bitmap Maker.
   - *Projects*: a card per project (for example *Slot-die coater ML*). Click it to see the apps of
     that project, with a *Back to Dashboard* button.
   - *Build Your Own*: *Learning* (tutorial notebooks for writing your own NOMAD analysis, opened
     in JupyterLab) and a link to a prompt you can paste into an AI chatbot so it can query your
     NOMAD data and write a custom script.
   - *Experimental / In Progress*: apps that are still being worked on (Electrochemical Analysis,
     SEM Crystal Counter, XPS Automated, LCC Calculator). They may be incomplete or change.
4. **What's New** (top right) opens the list of releases with the recent changes.

Your clicks on the dashboard are counted in the usage log (which app was opened), as for all
apps.

## For administrators

Which apps and groups are shown, and in which order, is a setting of each deployment, not of the
code. It is set with environment variables (usually in `oasis_local_config.py`):

- `HYSPRINT_DASHBOARD_HIDE_APPS`: comma-separated app folder names or card names to hide (the two
  sections *Learning* and *Projects* can be named too);
- `HYSPRINT_DASHBOARD_SHOW_APPS`: if set, the only apps shown;
- `HYSPRINT_DASHBOARD_GROUP_ORDER`: comma-separated group names in the order they should appear.

Names ignore case and spaces; an unknown name is logged and ignored. Hidden apps still exist in
the upload and can be opened directly. See `DEPLOYMENT.md` for details.

## Contact

Questions and problems: open an issue on
[nomad-pv-analysis-apps](https://github.com/nomad-hzb/nomad-pv-analysis-apps/issues).
