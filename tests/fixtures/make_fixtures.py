"""Generate sample .mrc fixture files for testing."""

from pymarc import Record, Field, Subfield, MARCWriter
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent


def make_record(
    control_num: str,
    title: str,
    dewey: str | None = None,
    lccn: str | None = None,
    isbn: str | None = None,
    oclc: str | None = None,
) -> Record:
    record = Record()
    record.add_field(Field(tag="001", data=control_num))

    if lccn:
        record.add_field(Field(tag="010", indicators=[" ", " "], subfields=[Subfield("a", lccn)]))

    if isbn:
        record.add_field(Field(tag="020", indicators=[" ", " "], subfields=[Subfield("a", isbn)]))

    if oclc:
        record.add_field(Field(tag="035", indicators=[" ", " "], subfields=[Subfield("a", f"(OCoLC){oclc}")]))

    record.add_field(Field(tag="245", indicators=["1", "0"], subfields=[Subfield("a", title)]))

    if dewey:
        record.add_field(Field(tag="082", indicators=["0", "4"], subfields=[Subfield("a", dewey), Subfield("2", "23")]))

    return record


def write_fixtures() -> None:
    records = [
        make_record("CTL001", "Python programming essentials", dewey="005.133", isbn="9780134444321", oclc="12345678"),
        make_record("CTL002", "The great American novel", dewey="813.54", lccn="2005012345", isbn="9780199535569"),
        make_record("CTL003", "No identifiers record", dewey="370.15"),
        make_record("CTL004", "Already LC — should be skipped", lccn="99001234"),  # no Dewey
        make_record("CTL005", "History of science", dewey="509", isbn="9780199559442", oclc="87654321"),
    ]

    with open(FIXTURES_DIR / "sample.mrc", "wb") as fh:
        writer = MARCWriter(fh)
        for r in records:
            writer.write(r)
        writer.close()


if __name__ == "__main__":
    write_fixtures()
    print("Fixtures written.")
