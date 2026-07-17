# HySPRINT Analysis Apps

A suite of web-based analysis and visualization tools for perovskite solar cell
research, developed by the SE-ALM group at
[Helmholtz-Zentrum Berlin (HZB)](https://www.helmholtz-berlin.de).

The apps are built around the [NOMAD Oasis](https://nomad-hzb-se.de/nomad-oasis/gui/)
infrastructure and follow FAIR data principles. They cover the full characterization
workflow: from JV curve analysis and MPPT tracking to EQE, TRPL, XRD, XPS, and more.

---

## Apps

| App | Description |
|---|---|
| JV Analysis | Current-voltage curve analysis and parameter extraction |
| MPPT Analysis | Maximum power point tracking analysis |
| EQE Analysis | External quantum efficiency analysis |
| AbsPL Analysis | Absorption and photoluminescence analysis |
| TRPL Analysis | Time-resolved photoluminescence analysis |
| Peak Explorer | Interactive peak identification across spectra |
| XRD Peak Finder | X-ray diffraction peak search and assignment |
| XPS Automated | Automated X-ray photoelectron spectroscopy analysis |
| NMR Analysis | Nuclear magnetic resonance data analysis |
| Electrochemical Analysis | Electrochemical measurement processing |
| SEM Crystal Counter | Automated crystal counting from SEM images |
| Global Analyzer | Cross-sample summary dashboard aggregating multiple measurement types |
| App Dashboard | Entry point and navigation hub for the suite |
| File Uploader | NOMAD file upload and metadata tagging |
| Excel Creator | Structured data export to Excel |
| Hansen Green Calculator | Hansen solubility parameter calculator |
| Wetting Envelope | Wetting and solvent compatibility visualization |
| Design of Experiments | DoE planning and analysis tools |
| Bitmap Maker | Substrate layout bitmap generation |
| Smart Databaser | Guided experiment/sample setup builder for structured NOMAD uploads |
| PeroDatabase Downloader | Pulls selected fields from NOMAD entries and exports them to CSV |

---

## Requirements

- Python 3.10 or higher
- A NOMAD account on the [HZB SE Oasis](https://nomad-hzb-se.de/nomad-oasis/gui/)
  (required for any app that reads from or writes to NOMAD)

> If you do not have a NOMAD account, register at the link above before
> attempting to run any app that connects to the Oasis.

---

## Installation

Clone the repository:

```bash
git clone https://github.com/EdNanda/nomad-pv-analysis-apps.git
cd nomad-pv-analysis-apps
```

Install the shared utility library:

```bash
pip install -e ./shared
```

Install and run a specific app:

```bash
cd apps/<AppName>
pip install -e .
voila <notebook>.ipynb
```

Each app folder has its own notebook file (check the folder for the exact
name, e.g. `jv-analysis.ipynb`, `hansen_app.ipynb`). The app will be available
at `http://localhost:8866` by default.

---

## Configuration

Most apps require a NOMAD Oasis URL and authentication token. Set these as
environment variables before running:

```bash
export NOMAD_URL=https://nomad-hzb-se.de/nomad-oasis
export NOMAD_TOKEN=your_token_here
export HYSPRINT_SERVER=hzb          # selects the data adapter for your server
```

Alternatively, create a `.env` file in the app folder (never commit this file):

```
NOMAD_URL=https://nomad-hzb-se.de/nomad-oasis
NOMAD_TOKEN=your_token_here
HYSPRINT_SERVER=hzb
```

---

## Repository Structure

```
nomad-pv-analysis-apps/
├── shared/                     # shared utilities used across all apps
│   └── hysprint_utils/
│       ├── api_calls.py
│       ├── auth_manager.py
│       ├── batch_selection.py
│       ├── error_handler.py
│       ├── plotting_utils.py
│       └── process_handling.py
├── apps/                       # one folder per app (see table above for the full list)
│   ├── JV-Analysis/
│   ├── Peak_Explorer/
│   └── ...
└── .gitignore
```

---

## Citation

> A citable reference for this repository is in preparation. In the meantime,
> please acknowledge use of these tools by linking to this repository.

---

## Contributing

Contributions, bug reports, and feature requests are welcome. Please open an
issue or pull request on GitHub.

If you are adapting these apps for a different NOMAD instance or server
environment, see the adapter documentation in `shared/hysprint_utils/adapters/`.

---

## Contact

**Dr. Edgar Nandayapa**
SE-ALM/HySPRINT Group, Helmholtz-Zentrum Berlin
GitHub: [@EdNanda](https://github.com/EdNanda)

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

## MIT License

```
MIT License

Copyright (c) 2025 Helmholtz-Zentrum Berlin für Materialien und Energie GmbH

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
