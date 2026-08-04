"""Review tables a human confirms, regenerated without losing the confirmations.

The spec asks for a small table where every resolution is confirmed or corrected
before it reaches the map. The awkward part is not the table, it is that it has to be
rebuilt after every batch of pasted chapters — thirty-seven times, if you validate as
you go — and each rebuild is a chance to quietly overwrite work somebody did by hand.

So the merge is the load-bearing piece here, and it has one rule: **a regeneration may
add rows and refresh proposals, and may never touch a human column.** A key that stops
being proposed is kept rather than deleted, since it may be a row somebody typed in.
And if the column list itself has lost the place confirmations live, the merge refuses
to write at all rather than doing most of the job.

Two conventions worth knowing when reading a table:

- An empty ``confirmed`` cell means the proposal is being used but nobody has
  checked it. That is reported as a count, never treated as agreement.
- ``n`` with no correction beside it means *this is not what I said it was, and I
  am not telling you what it is*. Downstream that reads as off-route, which is the
  safe direction: a place nobody vouched for does not move a pin.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "HUMAN_COLUMNS",
    "MergeRefusedError",
    "Table",
    "merge_rows",
    "read_table",
    "write_table",
]

# The columns a person edits. Everything else is regenerated from the extractions, and
# these are the ones a rebuild must carry across untouched.
HUMAN_COLUMNS = ("confirmed", "note")


class MergeRefusedError(Exception):
    """Raised when a regeneration would lose work somebody did by hand.

    Attributes:
        args: The reason, phrased so it names the fix.
    """


@dataclass(frozen=True, slots=True)
class Table:
    """A review table: its column order, and its rows keyed by the first column.

    Attributes:
        key_column: Which column identifies a row.
        columns: The full column order, as written.
        rows: The rows, keyed by their key column.
    """

    key_column: str
    columns: tuple[str, ...]
    rows: dict[str, dict[str, str]]

    def confirmed_count(self) -> int:
        """How many rows a human has signed off.

        Returns:
            The number of rows whose ``confirmed`` cell is non-empty.

        Examples:
            >>> Table("key", ("key", "confirmed"), {"a": {"key": "a", "confirmed": "y"}}
            ...       ).confirmed_count()
            1
        """
        return sum(1 for row in self.rows.values() if row.get("confirmed", "").strip())


def read_table(path: Path, key_column: str) -> Table:
    """Read an existing review table, or return an empty one.

    Args:
        path: The CSV.
        key_column: Which column identifies a row.

    Returns:
        The table. A missing file yields an empty table rather than an error — the first
        run has nothing to merge with, and that is not a problem.

    Contract:
        - Never raises for a missing file.
        - Preserves every column and cell exactly as written.
    """
    if not path.exists():
        return Table(key_column, (), {})
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        rows = {row[key_column]: dict(row) for row in reader if row.get(key_column)}
    return Table(key_column, columns, rows)


def merge_rows(
    existing: Table,
    proposed: Sequence[Mapping[str, str]],
    key_column: str,
    columns: Sequence[str],
    human_columns: Iterable[str] = HUMAN_COLUMNS,
) -> Table:
    """Fold freshly proposed rows into a table a human has been editing.

    Args:
        existing: What is on disk now.
        proposed: The rows this run computed.
        key_column: Which column identifies a row.
        columns: The column order to write.
        human_columns: The columns a person edits, which a merge must never overwrite.

    Returns:
        The merged table.

    Raises:
        MergeRefusedError: If a human column is missing from ``columns``, which would
            write a table with nowhere to put the confirmations. Refusing outright
            beats writing most of the file and losing the rest.

    Contract:
        - Every human column of every surviving row is carried across untouched.
        - The merged table has at least as many confirmed rows as ``existing``.
        - A key present only in ``existing`` is kept, so a hand-added row survives.
        - Idempotent: merging a table's own rows back into it changes nothing.

    Examples:
        >>> columns = ("key", "kind", "confirmed", "note")
        >>> old = Table("key", columns,
        ...             {"suez": {"key": "suez", "kind": "node", "confirmed": "y",
        ...                       "note": ""}})
        >>> new = merge_rows(old, [{"key": "suez", "kind": "waypoint"}], "key", columns)
        >>> new.rows["suez"]["confirmed"], new.rows["suez"]["kind"]
        ('y', 'waypoint')
    """
    human = tuple(human_columns)
    # Checked first, because it is the only way a confirmation can actually be lost:
    # a key that stops being proposed is kept below, and the human cells of a key that
    # is proposed are copied across. Editing the column list and forgetting `confirmed`
    # is the mistake this exists to catch.
    missing = [column for column in human if column not in columns]
    if missing:
        raise MergeRefusedError(
            f"the column list has no {missing} column(s), so there would be nowhere "
            "to keep the confirmations — refusing to write"
        )

    merged: dict[str, dict[str, str]] = {}

    for row in proposed:
        key = row[key_column]
        out = {column: str(row.get(column, "")) for column in columns}
        previous = existing.rows.get(key)
        if previous:
            for column in human:
                out[column] = previous.get(column, "")
            for column in columns:
                corrected = previous.get(column, "")
                if column.startswith("corrected_") and corrected:
                    out[column] = corrected
        merged[key] = out

    # A key that has dropped out of the proposals is still kept: it may be a row
    # somebody
    # added by hand, and deleting that would be exactly the loss this refuses to allow.
    for key, previous in existing.rows.items():
        if key not in merged:
            merged[key] = {column: previous.get(column, "") for column in columns}

    result = Table(key_column, tuple(columns), merged)
    if result.confirmed_count() < existing.confirmed_count():  # pragma: no cover
        # A backstop the precondition above should make unreachable. Kept because the
        # cost is one comparison and the thing it guards is somebody's afternoon.
        raise MergeRefusedError(
            f"the merge would drop "
            f"{existing.confirmed_count() - result.confirmed_count()} rows — "
            "refusing to write; check the key column for a change of spelling"
        )
    return result


def write_table(table: Table, path: Path) -> None:
    """Write a review table, rows sorted by key.

    Args:
        table: The table to write.
        path: Where to write it. Parent directories are created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table.columns))
        writer.writeheader()
        for key in sorted(table.rows):
            writer.writerow(table.rows[key])


def summarise(table: Table) -> str:
    """A one-line count for the run log.

    Args:
        table: The merged table.

    Returns:
        A sentence naming how many rows are confirmed, rejected and unchecked.

    Examples:
        >>> summarise(Table("key", ("key", "confirmed"), {
        ...     "a": {"key": "a", "confirmed": "y"},
        ...     "b": {"key": "b", "confirmed": ""},
        ... }))
        '2 rows: 1 confirmed, 0 rejected, 1 unchecked'
    """
    confirmed = rejected = 0
    for row in table.rows.values():
        cell = row.get("confirmed", "").strip().lower()
        if cell in {"y", "yes", "true", "1"}:
            confirmed += 1
        elif cell in {"n", "no", "false", "0"}:
            rejected += 1
    unchecked = len(table.rows) - confirmed - rejected
    return (
        f"{len(table.rows)} rows: {confirmed} confirmed, "
        f"{rejected} rejected, {unchecked} unchecked"
    )


def is_confirmed(cell: str) -> bool:
    """Whether a ``confirmed`` cell counts as a human saying yes.

    Args:
        cell: The cell contents.

    Returns:
        True only for an explicit yes. Blank is not agreement.

    Examples:
        >>> is_confirmed("y"), is_confirmed(""), is_confirmed("n")
        (True, False, False)
    """
    return cell.strip().lower() in {"y", "yes", "true", "1"}


def is_rejected(cell: str) -> bool:
    """Whether a ``confirmed`` cell counts as a human saying no.

    Args:
        cell: The cell contents.

    Returns:
        True for an explicit no.

    Examples:
        >>> is_rejected("n"), is_rejected(""), is_rejected("y")
        (True, False, False)
    """
    return cell.strip().lower() in {"n", "no", "false", "0"}
