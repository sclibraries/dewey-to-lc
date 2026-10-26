# dewey-to-lc

A Python CLI tool that adds a Library of Congress Classification (field **050**) to MARC records classed in Dewey Decimal, producing `.mrc` files ready for re-import into FOLIO.

## Which records are converted

The tool looks for a Dewey number in this order and uses the first one it finds:

1. **082** $a (any indicators)
2. **092** $a with both indicators blank (local Dewey)
3. **099** $a, when it looks like a Dewey number (starts with three digits, e.g. `944.033 C671 Zcou`)

If the 099 holds a non-Dewey local call number (e.g. `FOLIO C684t`) and there is no 082 or 092, the record is still looked up, but **only by its OCLC number** (035). Without an OCLC number it is skipped.

Records that already have an 050 are skipped. The 082, 092 and 099 fields are **never removed**; the tool only adds the 050.

## How It Works

There is no direct Dewey→LC concordance API. This tool looks up the same title in external library databases that already carry both classifications:

1. **OCLC WorldCat Metadata API** *(primary)* — finds the record by OCLC# (or searches by LCCN, then ISBN, to get an OCLC#) and takes the LC call number on that WorldCat record; only if the record has none does it take the most popular LC number libraries use for that work (which can come from another edition or format)
2. **loc.gov public API** *(fallback)* — searches the Library of Congress catalog by LCCN or ISBN
3. **Manual review queue** — records with no match are flagged in the CSV report for manual assignment via [Classification Web](https://classweb.org/)

For how the WorldCat lookup works in detail, see [docs/worldcat-api.md](docs/worldcat-api.md).

## Requirements

- Python 3.10+
- OCLC WorldCat Metadata API credentials (WSKey client ID + secret with the `WorldCatMetadataAPI` scope) — [request here](https://platform.worldcat.org/wskey/)
- *(Optional)* Classification Web subscription for manual review of unmatched records

## Installation

The project needs **Python 3.10 or newer**. Check which Python you have:

```bash
python3 --version
```

If it reports 3.9 or older, install a newer Python first. Macs ship with Python 3.9 from Apple's Command Line Tools, and its old pip fails with `File "setup.py" or "setup.cfg" not found. Directory cannot be installed in editable mode`.

1. Download and run the latest macOS installer from [python.org](https://www.python.org/downloads/macos/).
2. Find the version-numbered command it installed (plain `python3` may still point at Apple's 3.9):

   ```bash
   ls /usr/local/bin/ | grep -E '^python3\.[0-9]+$'
   ```

   Use the name it lists, such as `python3.14`, in the `venv` step below. If it lists nothing, the installer didn't finish; run it again.

Then clone the repo and install it into a virtual environment, replacing `python3.14` with your version:

```bash
git clone https://github.com/sclibraries/dewey-to-lc.git
cd dewey-to-lc
rm -rf .venv                  # remove any environment made with the old Python
python3.14 -m venv .venv
source .venv/bin/activate
python --version              # must report 3.10 or newer
python -m pip install --upgrade pip
python -m pip install -e .
dewey-to-lc --help            # confirms the install worked
```

Each time you open a new terminal, activate the environment before running the tool:

```bash
cd dewey-to-lc
source .venv/bin/activate
```

If something goes wrong, see [Troubleshooting](#troubleshooting).

## Configuration

In the project folder, copy `.env.example` to `.env` and fill in your credentials. `.env` is git-ignored; never commit it.

```bash
cp .env.example .env
```

```dotenv
WORLDCAT_CLIENT_ID=your_client_id
WORLDCAT_CLIENT_SECRET=your_client_secret
LOC_GOV_USER_AGENT=dewey-to-lc/0.1.0 (yourlibrary@example.org)
WORLDCAT_RATE_LIMIT=1.0
LOC_GOV_RATE_LIMIT=2.0
```

Without WorldCat credentials the tool still runs but only searches loc.gov, so far fewer records match.

Check that the credentials work (with the virtual environment active):

```bash
python check_credentials.py
```

It signs in to WorldCat, fetches the classification for one known record, and checks that loc.gov is reachable.

## Usage

### Export MARC records from FOLIO

In FOLIO, use **Data Export** to export the Dewey-classified records as a `.mrc` file. Ensure your export job includes the full MARC record (not just instance metadata).

The input must be **binary MARC** (`.mrc`). A MarcEdit text file (`.mrk`, lines like `=245  10$a...`) won't work, even if renamed; convert it first with MarcEdit's MarcMaker.

### Convert

```bash
dewey-to-lc convert records.mrc
```

Output paths are relative to the folder you run the command from, not to the input file:

| Output | Default | Holds |
|--------|---------|-------|
| Converted MARC | `./output/<input file name>` | Only the records converted in this run |
| CSV report | `./conversion_report.csv` | One row per record in the progress database |
| Progress database | `./progress.db` | Status of every record seen, kept between runs |

Records with no match, skipped records and errors are **not** written to the output `.mrc`; they are listed in the CSV report only. The summary printed at the end, like the report, counts every record in `progress.db`, including ones from earlier runs.

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `-o / --output-dir` | `./output` | Directory for converted `.mrc` files |
| `--report` | `./conversion_report.csv` | CSV report path |
| `--db` | `./progress.db` | SQLite progress database (for resume support) |
| `--worldcat-id` | `$WORLDCAT_CLIENT_ID` | WorldCat API client ID |
| `--worldcat-secret` | `$WORLDCAT_CLIENT_SECRET` | WorldCat API client secret |
| `--rate-limit` | `$WORLDCAT_RATE_LIMIT` or `1.0` | WorldCat requests per second |
| `--no-resume` | off | Re-process all records (ignore previous progress) |
| `-v / --verbose` | off | Enable debug logging |

### Multiple input files

```bash
dewey-to-lc convert batch1.mrc batch2.mrc batch3.mrc --output-dir ./output
```

### Rerunning and interrupted runs

Every run reads `progress.db` and **skips any record (matched by its 001) that an earlier run already handled**, whatever the outcome: converted, no match, skipped or error. That has three consequences:

- **After an interrupted run, rerun with `--no-resume`.** Converted records are written to the output `.mrc` only when a file finishes, so a resumed run would produce an output file missing the records converted before the interruption.
- **To retry `no_match` or `error` records**, or to rerun a corrected file, use `--no-resume` (or delete `progress.db`).
- **When starting a new batch**, delete `progress.db` and `conversion_report.csv` first, or point `--db` and `--report` at new files; otherwise the report also lists records from earlier batches.

```bash
dewey-to-lc convert records.mrc --no-resume
```

`dewey-to-lc resume records.mrc` is the same as `convert` with resume on and default paths; it doesn't accept `--db`, `--output-dir` or other options.

### Regenerate the CSV report

```bash
dewey-to-lc report --db ./progress.db --output ./conversion_report.csv
```

## CSV Report

The report has one row per record:

| Column | Description |
|--------|-------------|
| `control_number` | MARC 001 control number |
| `title` | Title from 245 field |
| `old_dewey` | Original Dewey number, or the local 099 call number when it isn't Dewey |
| `dewey_field` | Where that number came from: `082`, `092`, `099` or `099 (not Dewey)` |
| `new_lc_class` | LC classification number (050 $a) |
| `new_lc_item` | LC item number (050 $b) |
| `new_lc_full` | Full LC call number |
| `lookup_source` | `worldcat`, `loc.gov`, or empty |
| `status` | `converted`, `no_match`, `skipped`, `error` (or `pending` if a run stopped before reaching it) |
| `error_message` | Error detail if status is `error` |
| `processed_at` | When the record was processed (UTC) |

**Records with `no_match`** — these are not in the output `.mrc`. Look each one up in Classification Web and add the LC number to the record directly in FOLIO.

**Check `converted` records too.** WorldCat returns the LC number most libraries use for the work, which can come from a different edition or a microform/reprint. Spot-check, especially older and rare books and rows where `dewey_field` is `099 (not Dewey)`.

## Loading Converted Records Back into FOLIO

The converted records are full MARC bib records with the new 050 added, so they are loaded as an **update (overlay) of the existing MARC bib**. Test with a single record before loading a batch.

### 1. Configure Data Import profiles (one-time setup)

In FOLIO **Settings → Data Import**, create:

- **Match Profile**: incoming MARC Bibliographic `999 ff $i` → Instance UUID
  *(records exported from FOLIO carry it; or match `001` → Instance HRID)*
- **Action Profile**: Update → MARC Bibliographic record
- **Mapping Profile**: Update MARC Bibliographic record (no field mappings needed; protect any local fields your library protects)
- **Job Profile**: MARC as the data type, combining the match and action profiles

FOLIO then re-derives the Instance from the updated MARC record, and the default MARC-to-Instance mapping adds the 050 to the Instance's **Classification** list as an LC classification.

**What this does not change:** holdings and item call numbers. In a FOLIO export they appear in fields such as 852/952 (e.g. `944.033 C671 Zcou`); the tool leaves them alone and importing a bib update doesn't touch holdings. Changing shelf call numbers is a separate holdings update.

### 2. Import

Upload the converted `.mrc` files via **Data Import** in FOLIO, or use the [`folio_data_import`](https://pypi.org/project/folio_data_import/) CLI (checked against version 0.6.9):

```bash
python -m pip install folio_data_import
export FOLIO_GATEWAY_URL="https://your-folio.example.org"
export FOLIO_TENANT_ID="your-tenant"
export FOLIO_USERNAME="your-username"
export FOLIO_PASSWORD="your-password"
folio-data-import marc --marc-file-path output/records.mrc
```

It prompts you to pick the job profile, or pass `--import-profile-name "<your job profile>"`.

### 3. Verify

After import, spot-check 10–20 records in FOLIO Inventory to confirm:
- The Instance's Classification list shows the new LC number
- The MARC record has the new 050 and still has its 082/092/099 fields
- No unintended field changes

## Troubleshooting

Common problems, roughly in the order you'd meet them.

### Installing

**`ERROR: File "setup.py" or "setup.cfg" not found. Directory cannot be installed in editable mode`**

Your Python is too old (usually the Python 3.9 that comes with a Mac). Install Python 3.10 or newer and build the virtual environment with it, as in [Installation](#installation).

**`Defaulting to user installation because normal site-packages is not writeable`**

pip is installing into the system Python instead of the virtual environment. Activate the environment first (`source .venv/bin/activate`), then rerun the install.

**`python --version` still says 3.9 after installing a new Python**

The `.venv` folder was built with the old Python, or plain `python3` still points at it. Rebuild it with the version-numbered command:

```bash
deactivate 2>/dev/null
rm -rf .venv
python3.14 -m venv .venv      # use the version you installed
source .venv/bin/activate
python --version
python -m pip install -e .
```

**`ls /usr/local/bin/ | grep -E '^python3\.[0-9]+$'` lists nothing**

The python.org installer didn't finish. Run it again.

**`command not found: dewey-to-lc`**

The virtual environment isn't active in this terminal window. Run `cd dewey-to-lc` and `source .venv/bin/activate`. If it still isn't found, the install didn't complete; rerun `python -m pip install -e .`.

### Credentials

**`⚠  WorldCat credentials not provided — falling back to loc.gov only.`**

The tool can't find `.env`, or it's missing `WORLDCAT_CLIENT_ID` / `WORLDCAT_CLIENT_SECRET`. Make sure the file is named exactly `.env` (not `.env.txt` or `env`) and sits in the `dewey-to-lc` folder. Without it, most records end up `no_match`.

**`Failed to create WorldCat session: ... "invalid clientId"`** (or any 401)

The client ID or secret is wrong, or the key lacks the `WorldCatMetadataAPI` scope. The run keeps going but every record falls back to loc.gov, so watch for this line. Check the values in `.env` and run `python check_credentials.py`.

### Input files

**`Error: Invalid value for 'INPUT_FILES...': Path 'records.mrc' does not exist.`**

The path is relative to the folder you're in. Give the full path (e.g. `~/Downloads/records.mrc`) or `cd` to the file's folder.

**`AttributeError: 'NoneType' object has no attribute 'get_fields'`**

The file isn't binary MARC. A MarcEdit `.mrk` text file causes this even when renamed to `.mrc`. Export from FOLIO Data Export, or convert the `.mrk` with MarcEdit's MarcMaker.

### Results

**A record with a Dewey number shows `skipped`**

Most often an earlier run already handled that 001, and `progress.db` remembers it. Rerun with `--no-resume`, or delete `progress.db`. Otherwise the record:
- already has an 050,
- has its Dewey number only in a 092 whose indicators aren't both blank, or
- has a non-Dewey 099 and no OCLC number (035).

**Lots of `no_match`**

Check the run's first lines for the credentials warnings above. Records with no OCLC number, LCCN or ISBN can't be looked up at all.

**The LC number looks wrong for the book**

WorldCat returns the number most libraries use for the whole work, which can come from a different edition, a reprint or a microform set. Check older and rare books, and rows where `dewey_field` is `099 (not Dewey)`, before importing.

**Can't find the output files**

They're written relative to the folder you ran the command from: `./output/`, `./conversion_report.csv` and `./progress.db`. Run `ls output` there.

**The output `.mrc` is missing records the report says were converted**

The run was interrupted, then resumed. Rerun the file with `--no-resume`.

**The report lists records from an older batch**

The report covers everything in `progress.db`. Delete `progress.db` and `conversion_report.csv` before a new batch, or use new `--db` and `--report` paths.

**Runs are slow**

That's the rate limit: one WorldCat request per second by default, and a record can take several requests. It is set by `WORLDCAT_RATE_LIMIT` in `.env` or `--rate-limit`; stay within what OCLC allows for your key.

### After importing into FOLIO

**FOLIO still shows the Dewey call number**

The tool updates the bib record, so the LC number appears in the Instance's Classification list. Holdings and item call numbers (852/952) are not changed; that's a separate holdings update.

## Development

```bash
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest
```

## Project Structure

```
check_credentials.py  # One-off check that WorldCat and loc.gov respond
docs/worldcat-api.md  # How the WorldCat lookup works, with real responses
src/dewey_to_lc/
├── cli.py          # Click CLI (convert / report / resume commands)
├── converter.py    # Batch conversion orchestrator
├── marc_utils.py   # pymarc field extraction and manipulation
├── progress.py     # SQLite-based resume tracking
├── report.py       # CSV report generation
└── lookup/
    ├── base.py     # Abstract LookupService interface
    ├── worldcat.py # WorldCat Metadata API
    └── loc_gov.py  # loc.gov public API fallback
```
