"""CLI entry point for dewey-to-lc."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from dewey_to_lc.converter import Converter
from dewey_to_lc.lookup.loc_gov import LocGovLookup
from dewey_to_lc.lookup.worldcat import WorldCatLookup
from dewey_to_lc.progress import ProgressTracker
from dewey_to_lc.report import print_summary, write_csv_report

load_dotenv()


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _build_lookup_services(worldcat_id: str | None, worldcat_secret: str | None, rate_limit: float):
    """Build the ordered list of lookup services based on available credentials."""
    services = []

    if worldcat_id and worldcat_secret:
        services.append(
            WorldCatLookup(
                client_id=worldcat_id,
                client_secret=worldcat_secret,
                rate_limit=rate_limit,
            )
        )
    else:
        click.echo(
            "⚠  WorldCat credentials not provided — falling back to loc.gov only.", err=True
        )

    user_agent = os.environ.get(
        "LOC_GOV_USER_AGENT", "dewey-to-lc/0.1.0 (library-automation)"
    )
    loc_rate = float(os.environ.get("LOC_GOV_RATE_LIMIT", "2.0"))
    services.append(LocGovLookup(user_agent=user_agent, rate_limit=loc_rate))

    return services


@click.group()
@click.version_option(version="0.1.0", prog_name="dewey-to-lc")
def cli() -> None:
    """Convert MARC records from Dewey Decimal (082) to LC Classification (050)."""


@cli.command("convert")
@click.argument("input_files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o", "--output-dir",
    default="./output",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Directory for converted .mrc files.",
)
@click.option(
    "--db",
    default="./progress.db",
    show_default=True,
    type=click.Path(path_type=Path),
    help="SQLite progress database for resume support.",
)
@click.option(
    "--report",
    default="./conversion_report.csv",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Path for the CSV conversion report.",
)
@click.option(
    "--worldcat-id",
    envvar="WORLDCAT_CLIENT_ID",
    default=None,
    help="OCLC WorldCat API client ID (or set WORLDCAT_CLIENT_ID env var).",
)
@click.option(
    "--worldcat-secret",
    envvar="WORLDCAT_CLIENT_SECRET",
    default=None,
    help="OCLC WorldCat API client secret (or set WORLDCAT_CLIENT_SECRET env var).",
)
@click.option(
    "--rate-limit",
    default=1.0,
    show_default=True,
    type=float,
    help="WorldCat API requests per second.",
)
@click.option(
    "--no-resume",
    is_flag=True,
    default=False,
    help="Ignore previous progress and re-process all records.",
)
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable debug logging.")
def convert_cmd(
    input_files: tuple[Path, ...],
    output_dir: Path,
    db: Path,
    report: Path,
    worldcat_id: str | None,
    worldcat_secret: str | None,
    rate_limit: float,
    no_resume: bool,
    verbose: bool,
) -> None:
    """Convert one or more .mrc files from Dewey to LC classification.

    INPUT_FILES: One or more binary MARC (.mrc) files to convert.
    """
    _setup_logging(verbose)
    services = _build_lookup_services(worldcat_id, worldcat_secret, rate_limit)

    if not services:
        click.echo("✗ No lookup services available. Provide WorldCat credentials or check connectivity.", err=True)
        sys.exit(1)

    tracker = ProgressTracker(db)
    converter = Converter(
        lookup_services=services,
        tracker=tracker,
        output_dir=output_dir,
        resume=not no_resume,
    )

    try:
        stats = converter.convert_files(list(input_files))
    finally:
        for svc in services:
            svc.close()

    print_summary(tracker)

    report_count = write_csv_report(tracker, report)
    click.echo(f"✓ CSV report written: {report} ({report_count} records)")
    click.echo(f"✓ Converted .mrc files in: {output_dir}/")

    if stats.no_match > 0:
        click.echo(
            f"\n⚠  {stats.no_match} record(s) had no LC match. "
            "Review these in the CSV report and assign manually via Classification Web.",
            err=True,
        )

    tracker.close()


@cli.command("report")
@click.option(
    "--db",
    default="./progress.db",
    show_default=True,
    type=click.Path(exists=True, path_type=Path),
    help="SQLite progress database.",
)
@click.option(
    "--output",
    default="./conversion_report.csv",
    show_default=True,
    type=click.Path(path_type=Path),
    help="Output CSV path.",
)
def report_cmd(db: Path, output: Path) -> None:
    """Generate (or regenerate) the CSV report from an existing progress database."""
    tracker = ProgressTracker(db)
    print_summary(tracker)
    count = write_csv_report(tracker, output)
    click.echo(f"✓ Report written: {output} ({count} records)")
    tracker.close()


@cli.command("resume")
@click.argument("input_files", nargs=-1, required=True, type=click.Path(exists=True, path_type=Path))
@click.pass_context
def resume_cmd(ctx: click.Context, input_files: tuple[Path, ...]) -> None:
    """Resume a previously interrupted conversion run.

    Equivalent to running `convert` without --no-resume.
    Reads configuration from the environment / .env file.
    """
    ctx.invoke(convert_cmd, input_files=input_files)


if __name__ == "__main__":
    cli()
