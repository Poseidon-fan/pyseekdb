"""
Integration tests for DIFF TABLE functionality.

Tests the diff functionality against real databases using plain (non-LOB) tables,
since DIFF TABLE does not support LOB column types (e.g., vectors).

Tests include:
- Diff between identical tables (no differences)
- Diff detecting conflicting rows (same key, different values)
- Diff detecting rows unique to either table
- Diff with empty tables
- Diff through Collection API with proper table naming
"""

import contextlib
import logging
import time

import pytest

logger = logging.getLogger(__name__)


class TestCollectionDiff:
    """Tests for DIFF TABLE using real database connections."""

    def _is_diff_merge_enabled(self, client) -> bool:
        """Check if diff/merge is enabled for the given client."""
        try:
            return client._server._diff_merge_enabled()
        except Exception:
            logger.exception("Failed to check if diff/merge is enabled")
            return False

    def _execute(self, client, sql):
        """Execute SQL via the underlying server client."""
        return client._server._execute(sql)

    def _cleanup_tables(self, client, *table_names):
        """Drop tables, ignoring errors."""
        for name in table_names:
            with contextlib.suppress(Exception):
                self._execute(client, f"DROP TABLE IF EXISTS `{name}`")

    def test_diff_identical_tables(self, db_client):
        """
        Test diff between two identical tables returns empty result.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_base_{ts}"
        copy_table = f"test_diff_copy_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(
                db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90), (3, 'Charlie', 70)"
            )
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{copy_table}`")

            result = self._execute(db_client, f"DIFF TABLE `{copy_table}` AGAINST `{base_table}`")
            diff_rows = result if result else []
            print(f"\n✅ Diff between identical tables: {len(diff_rows)} rows")
            assert len(diff_rows) == 0, f"Expected 0 diff rows for identical tables, got {len(diff_rows)}"
        finally:
            self._cleanup_tables(db_client, copy_table, base_table)

    def test_diff_with_added_rows(self, db_client):
        """
        Test diff detects rows unique to the incoming table.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_base_{ts}"
        incoming_table = f"test_diff_added_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{incoming_table}`")

            # Add a new row to incoming
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            result = self._execute(db_client, f"DIFF TABLE `{incoming_table}` AGAINST `{base_table}`")
            diff_rows = result if result else []
            print(f"\n✅ Diff with added rows: {len(diff_rows)} diff rows")
            assert len(diff_rows) > 0, "Expected diff rows for table with added data"
        finally:
            self._cleanup_tables(db_client, incoming_table, base_table)

    def test_diff_with_modified_rows(self, db_client):
        """
        Test diff detects conflicting rows (same key, different values).
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_base_{ts}"
        incoming_table = f"test_diff_modified_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(
                db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90), (3, 'Charlie', 70)"
            )
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{incoming_table}`")

            # Modify a row in incoming
            self._execute(db_client, f"UPDATE `{incoming_table}` SET score = 85 WHERE id = 1")

            result = self._execute(db_client, f"DIFF TABLE `{incoming_table}` AGAINST `{base_table}`")
            diff_rows = result if result else []
            print(f"\n✅ Diff with modified rows: {len(diff_rows)} diff rows")
            # Conflict produces 2 rows (one from each table)
            assert len(diff_rows) == 2, f"Expected 2 diff rows for one modified row, got {len(diff_rows)}"
        finally:
            self._cleanup_tables(db_client, incoming_table, base_table)

    def test_diff_with_deleted_rows(self, db_client):
        """
        Test diff detects rows unique to the current (baseline) table.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_base_{ts}"
        incoming_table = f"test_diff_deleted_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(
                db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90), (3, 'Charlie', 70)"
            )
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{incoming_table}`")

            # Delete a row from incoming
            self._execute(db_client, f"DELETE FROM `{incoming_table}` WHERE id = 2")

            result = self._execute(db_client, f"DIFF TABLE `{incoming_table}` AGAINST `{base_table}`")
            diff_rows = result if result else []
            print(f"\n✅ Diff with deleted rows: {len(diff_rows)} diff rows")
            assert len(diff_rows) > 0, "Expected diff rows when incoming has deleted data"
        finally:
            self._cleanup_tables(db_client, incoming_table, base_table)

    def test_diff_is_readonly(self, db_client):
        """
        Test that diff does not modify either table.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_base_{ts}"
        incoming_table = f"test_diff_ro_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{incoming_table}`")
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            count_base_before = self._execute(db_client, f"SELECT COUNT(*) AS cnt FROM `{base_table}`")
            count_incoming_before = self._execute(db_client, f"SELECT COUNT(*) AS cnt FROM `{incoming_table}`")

            # Perform diff
            self._execute(db_client, f"DIFF TABLE `{incoming_table}` AGAINST `{base_table}`")

            count_base_after = self._execute(db_client, f"SELECT COUNT(*) AS cnt FROM `{base_table}`")
            count_incoming_after = self._execute(db_client, f"SELECT COUNT(*) AS cnt FROM `{incoming_table}`")

            assert count_base_before == count_base_after, "Base table should not be modified by diff"
            assert count_incoming_before == count_incoming_after, "Incoming table should not be modified by diff"
            print("\n✅ Diff is read-only verified")
        finally:
            self._cleanup_tables(db_client, incoming_table, base_table)

    def test_diff_empty_tables(self, db_client):
        """
        Test diff between two empty tables returns empty result.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        base_table = f"test_diff_empty_base_{ts}"
        copy_table = f"test_diff_empty_copy_{ts}"

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50))")
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{copy_table}`")

            result = self._execute(db_client, f"DIFF TABLE `{copy_table}` AGAINST `{base_table}`")
            diff_rows = result if result else []
            print(f"\n✅ Diff between empty tables: {len(diff_rows)} rows")
            assert len(diff_rows) == 0, f"Expected 0 diff rows for empty tables, got {len(diff_rows)}"
        finally:
            self._cleanup_tables(db_client, copy_table, base_table)

    def test_diff_via_collection_api(self, db_client):
        """
        Test diff through the Collection.diff() public API.
        Creates tables with the SDK naming convention (c$v1$ prefix).
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        from pyseekdb.client.collection import Collection
        from pyseekdb.client.meta_info import CollectionNames

        ts = int(time.time() * 1000)
        base_name = f"test_diff_api_base_{ts}"
        incoming_name = f"test_diff_api_incoming_{ts}"
        base_table = CollectionNames.table_name(base_name)
        incoming_table = CollectionNames.table_name(incoming_name)

        try:
            self._execute(db_client, f"CREATE TABLE `{base_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)")
            self._execute(db_client, f"INSERT INTO `{base_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{base_table}` TO `{incoming_table}`")
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            # Create Collection objects pointing to these tables (collection_id=None -> v1 naming)
            server = db_client._server
            base_col = Collection(client=server, name=base_name, collection_id=None)
            incoming_col = Collection(client=server, name=incoming_name, collection_id=None)

            # Call the public API
            diff_rows = incoming_col.diff(base_col)
            print(f"\n✅ Diff via Collection API: {len(diff_rows)} diff rows")
            assert len(diff_rows) > 0, "Expected diff rows via Collection API"
        finally:
            self._cleanup_tables(db_client, incoming_table, base_table)
