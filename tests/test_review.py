import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from verne80.review import (
    MergeRefusedError,
    Table,
    carry_unowned,
    is_confirmed,
    is_rejected,
    merge_rows,
    orphans,
    prune,
    read_table,
    summarise,
    write_table,
)

COLUMNS = ("key", "kind", "why", "confirmed", "corrected_kind", "note")


def table(**rows):
    return Table(
        "key",
        COLUMNS,
        {
            key: {"key": key, **{column: "" for column in COLUMNS[1:]}, **cells}
            for key, cells in rows.items()
        },
    )


def proposal(key, **cells):
    return {"key": key, **cells}


class TestMergeKeepsHumanWork:
    def test_a_confirmed_row_survives_regeneration(self):
        old = table(suez={"kind": "node", "confirmed": "y"})
        new = merge_rows(old, [proposal("suez", kind="waypoint")], "key", COLUMNS)
        assert new.rows["suez"]["confirmed"] == "y"

    def test_a_fresh_proposal_replaces_the_machine_columns(self):
        old = table(suez={"kind": "node", "why": "old reason", "confirmed": "y"})
        new = merge_rows(
            old, [proposal("suez", kind="waypoint", why="new reason")], "key", COLUMNS
        )
        assert new.rows["suez"]["kind"] == "waypoint"
        assert new.rows["suez"]["why"] == "new reason"

    def test_a_correction_wins_over_the_proposal(self):
        old = table(bombay={"kind": "unknown", "corrected_kind": "node"})
        new = merge_rows(old, [proposal("bombay", kind="off_route")], "key", COLUMNS)
        assert new.rows["bombay"]["corrected_kind"] == "node"

    def test_a_note_survives(self):
        old = table(aden={"note": "check the coaling stop"})
        new = merge_rows(old, [proposal("aden", kind="waypoint")], "key", COLUMNS)
        assert new.rows["aden"]["note"] == "check the coaling stop"

    def test_a_hand_added_row_is_not_deleted(self):
        """A key nobody proposed may be one somebody typed in themselves."""
        old = table(kholby={"kind": "waypoint", "confirmed": "y"})
        new = merge_rows(old, [proposal("suez", kind="node")], "key", COLUMNS)
        assert set(new.rows) == {"kholby", "suez"}

    def test_a_new_place_arrives_unchecked(self):
        new = merge_rows(table(), [proposal("aden", kind="waypoint")], "key", COLUMNS)
        assert new.rows["aden"]["confirmed"] == ""


class TestMergeRefusal:
    def test_dropping_the_confirmed_column_refuses_to_write(self):
        """The one way a confirmation can actually be lost.

        A key that stops being proposed is kept, and the human cells of a key that is
        proposed are copied across — so the real hazard is somebody editing the column
        list and forgetting that confirmations need somewhere to live.
        """
        old = table(suez={"kind": "node", "confirmed": "y"})
        with pytest.raises(MergeRefusedError, match="nowhere"):
            merge_rows(old, [proposal("suez", kind="node")], "key", ("key", "kind"))

    def test_a_key_that_stops_being_proposed_is_still_not_lost(self):
        old = table(suez={"kind": "node", "confirmed": "y"})
        assert merge_rows(old, [], "key", COLUMNS).rows["suez"]["confirmed"] == "y"


class TestPruning:
    """Keys strand when a key's shape changes; merge_rows deliberately never deletes."""

    def test_orphans_are_reported_even_without_prune(self):
        old = table(mongolia={}, **{'"mongolia"': {}})
        assert orphans(old, ["mongolia"]) == ['"mongolia"']

    def test_pruning_removes_an_untouched_orphan(self):
        old = table(mongolia={}, suez={})
        pruned, removed = prune(old, ["suez"])
        assert removed == ["suez"]
        assert set(pruned.rows) == {"mongolia"}

    def test_pruning_never_removes_a_confirmed_row(self):
        old = table(suez={"confirmed": "y"})
        pruned, removed = prune(old, ["suez"])
        assert removed == []
        assert set(pruned.rows) == {"suez"}

    def test_pruning_never_removes_a_corrected_row(self):
        old = table(suez={"corrected_kind": "waypoint"})
        assert prune(old, ["suez"])[1] == []

    def test_pruning_never_removes_a_noted_row(self):
        assert prune(table(suez={"note": "ask Zoli"}), ["suez"])[1] == []

    def test_pruning_ignores_a_key_it_was_not_given(self):
        old = table(suez={}, aden={})
        assert set(prune(old, ["suez"])[0].rows) == {"aden"}

    def test_pruning_nothing_changes_nothing(self):
        old = table(suez={})
        assert prune(old, [])[0].rows == old.rows


class TestRoundTrip:
    def test_a_written_table_reads_back_identically(self, tmp_path):
        original = table(suez={"kind": "node", "confirmed": "y", "note": "a, comma"})
        path = tmp_path / "places.csv"
        write_table(original, path)
        assert read_table(path, "key").rows == original.rows

    def test_a_missing_file_reads_as_empty(self, tmp_path):
        assert read_table(tmp_path / "absent.csv", "key").rows == {}


class TestCells:
    @pytest.mark.parametrize("cell", ["y", "Y", "yes", "true", "1"])
    def test_a_yes_is_a_yes(self, cell):
        assert is_confirmed(cell)

    @pytest.mark.parametrize("cell", ["n", "no", "false", "0"])
    def test_a_no_is_a_no(self, cell):
        assert is_rejected(cell)

    def test_blank_is_neither(self):
        """Nobody looked at it. That is not the same as agreeing with it."""
        assert not is_confirmed("") and not is_rejected("")

    def test_the_summary_counts_all_three(self):
        counted = summarise(
            table(a={"confirmed": "y"}, b={"confirmed": "n"}, c={"confirmed": ""})
        )
        assert counted == "3 rows: 1 confirmed, 1 rejected, 1 unchecked"


class TestMergeProperties:
    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.tuples(
                st.text(alphabet="abcdef", min_size=1, max_size=4),
                st.sampled_from(["", "y", "n"]),
            ),
            max_size=8,
        )
    )
    def test_merging_never_reduces_the_confirmed_count(self, pairs):
        old = table(**{key: {"confirmed": cell} for key, cell in pairs})
        new = merge_rows(old, [proposal(key) for key, _ in pairs], "key", COLUMNS)
        assert new.confirmed_count() >= old.confirmed_count()

    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.text(alphabet="abcdef", min_size=1, max_size=4), unique=True, max_size=8
        )
    )
    def test_merging_is_idempotent(self, keys):
        proposals = [proposal(key, kind="node") for key in keys]
        once = merge_rows(table(), proposals, "key", COLUMNS)
        twice = merge_rows(once, proposals, "key", COLUMNS)
        assert twice.rows == once.rows

    @settings(max_examples=150, deadline=None)
    @given(
        st.lists(
            st.text(alphabet="abcdef", min_size=1, max_size=4), unique=True, max_size=8
        )
    )
    def test_every_proposed_key_survives(self, keys):
        merged = merge_rows(table(), [proposal(key) for key in keys], "key", COLUMNS)
        assert set(merged.rows) == set(keys)


class TestCarryingAnotherStagesColumns:
    """05_places re-proposing must not empty the gazetteer's coordinates."""

    def table(self):
        return Table(
            "key",
            ("key", "kind", "lat", "confirmed", "note"),
            {
                "suez": {
                    "key": "suez",
                    "kind": "node",
                    "lat": "29.97",
                    "confirmed": "",
                    "note": "",
                }
            },
        )

    def test_a_coordinate_survives_a_re_propose(self):
        """Losing it un-anchors the next re-rank, and nothing announces it."""
        rows, _ = carry_unowned(
            self.table(), [{"key": "suez", "kind": "waypoint"}], "key", ("key", "kind")
        )
        assert rows[0]["lat"] == "29.97"

    def test_the_proposal_still_wins_for_the_columns_it_owns(self):
        rows, _ = carry_unowned(
            self.table(), [{"key": "suez", "kind": "waypoint"}], "key", ("key", "kind")
        )
        assert rows[0]["kind"] == "waypoint"

    def test_an_owned_column_may_be_emptied_on_purpose(self):
        rows, _ = carry_unowned(
            self.table(), [{"key": "suez", "kind": ""}], "key", ("key", "kind")
        )
        assert rows[0]["kind"] == ""

    def test_a_new_key_carries_nothing(self):
        rows, _ = carry_unowned(
            self.table(), [{"key": "aden", "kind": "node"}], "key", ("key", "kind")
        )
        assert "lat" not in rows[0]

    def test_the_foreign_columns_are_kept_in_the_column_order(self):
        _, columns = carry_unowned(self.table(), [], "key", ("key", "kind"))
        assert columns == ("key", "kind", "lat", "confirmed", "note")

    def test_no_column_is_listed_twice(self):
        _, columns = carry_unowned(self.table(), [], "key", ("key", "kind", "lat"))
        assert len(columns) == len(set(columns))

    def test_the_result_still_merges_without_refusing(self):
        """The column list it returns must still hold the human columns."""
        rows, columns = carry_unowned(
            self.table(), [{"key": "suez", "kind": "waypoint"}], "key", ("key", "kind")
        )
        merged = merge_rows(self.table(), rows, "key", columns)
        assert merged.rows["suez"]["lat"] == "29.97"
