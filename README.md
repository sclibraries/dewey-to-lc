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

1. **OCLC WorldCat Search API v2** *(primary)* — queries by OCLC#, LCCN, or ISBN; extracts the 050 field from the matched MARCXML record
2. **loc.gov public API** *(fallback)* — searches the Library of Congress catalog by LCCN or ISBN
3. **Manual review queue** — records with no match are flagged in the CSV report for manual assignment via [Classification Web](https://classweb.org/)

## Requirements

- Python 3.10+
- OCLC WorldCat API v2 credentials (WSKey client ID + secret) — [register here](https://platform.worldcat.org/wskey/)
- *(Optional)* Classification Web subscription for manual review of unmatched records

## Installation

```bash
git clone <repo>
cd dewey-to-lc
python3 -m pip install -e .
```

## Configuration

Copy `.env.example` to `.env` and fill in your credentials:

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

## Usage

### Export MARC records from FOLIO

In FOLIO, use **Data Export** to export the Dewey-classified records as a `.mrc` file. Ensure your export job includes the full MARC record (not just instance metadata).

### Convert

```bash
dewey-to-lc convert records.mrc \
  --output-dir ./output \
  --report ./conversion_report.csv \
  --db ./progress.db
```

Options:
| Flag | Default | Description |
|------|---------|-------------|
| `-o / --output-dir` | `./output` | Directory for converted `.mrc` files |
| `--report` | `./conversion_report.csv` | CSV report path |
| `--db` | `./progress.db` | SQLite progress database (for resume support) |
| `--worldcat-id` | `$WORLDCAT_CLIENT_ID` | WorldCat API client ID |
| `--worldcat-secret` | `$WORLDCAT_CLIENT_SECRET` | WorldCat API client secret |
| `--rate-limit` | `1.0` | WorldCat requests per second |
| `--no-resume` | off | Re-process all records (ignore previous progress) |
| `-v / --verbose` | off | Enable debug logging |

### Multiple input files

```bash
dewey-to-lc convert batch1.mrc batch2.mrc batch3.mrc --output-dir ./output
```

### Resume an interrupted run

```bash
dewey-to-lc resume records.mrc
# or equivalently:
dewey-to-lc convert records.mrc  # resume is on by default
```

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
| `status` | `converted`, `no_match`, `skipped`, `error` |
| `error_message` | Error detail if status is `error` |

**Records with `no_match`** — Open Classification Web, search for each title by identifier, and manually assign the LC call number. These records can be edited directly in FOLIO after import.

## Loading Converted Records Back into FOLIO

### 1. Configure Data Import profiles (one-time setup)

In FOLIO **Settings → Data Import**, create:

- **Match Profile**: Match on MARC field `001` → Instance HRID
  *(or `999 $i` if your records carry the Instance UUID)*
- **Action Profile**: Update existing Source Record Storage (SRS) MARC Bib + Instance
- **Mapping Profile**: Map 050 $a + $b → Instance call number
- **Job Profile**: Combine the above profiles

### 2. Import

Upload the converted `.mrc` files via **FOLIO Data Import UI**, or use the [`folio_data_import`](https://pypi.org/project/folio_data_import/) CLI:

```bash
pip install folio_data_import
folio-marc-import \
  --tenant your-tenant \
  --okapi-url https://your-folio.example.org \
  --username admin \
  --password secret \
  --job-profile-name "Overlay Bib — Dewey to LC" \
  output/records.mrc
```

### 3. Verify

After import, spot-check 10–20 records in FOLIO Inventory to confirm:
- Dewey fields (082/092/099) are still present
- New LC call number is present and correctly formatted
- No unintended field changes

## Development

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

## Project Structure

```
src/dewey_to_lc/
├── cli.py          # Click CLI (convert / report / resume commands)
├── converter.py    # Batch conversion orchestrator
├── marc_utils.py   # pymarc field extraction and manipulation
├── progress.py     # SQLite-based resume tracking
├── report.py       # CSV report generation
└── lookup/
    ├── base.py     # Abstract LookupService interface
    ├── worldcat.py # WorldCat Search API v2
    └── loc_gov.py  # loc.gov public API fallback
```
