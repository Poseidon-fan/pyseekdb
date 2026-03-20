"""
Integration tests for MERGE TABLE functionality.

Tests the merge functionality against real databases using plain (non-LOB) tables,
since MERGE TABLE does not support LOB column types (e.g., vectors).

Tests include:
- Merge with no conflicts (new rows inserted)
- Merge with THEIRS strategy (incoming overwrites on conflict)
- Merge with OURS strategy (current preserved on conflict)
- Merge with FAIL strategy (error on conflict, rollback)
- Invalid strategy parameter handling
- Merge through Collection API with proper table naming
"""

import contextlib
import logging
import time

import pymysql.err
import pytest

logger = logging.getLogger(__name__)


class TestCollectionMerge:
    """Tests for MERGE TABLE using real database connections."""

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

    def _get_count(self, client, table_name):
        """Get row count for a table."""
        result = self._execute(client, f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
        if isinstance(result[0], dict):
            return result[0]["cnt"]
        return result[0][0]

    def _get_row(self, client, table_name, row_id):
        """Get a single row by id."""
        result = self._execute(client, f"SELECT * FROM `{table_name}` WHERE id = {row_id}")
        return result[0] if result else None

    def _cleanup_tables(self, client, *table_names):
        """Drop tables, ignoring errors."""
        for name in table_names:
            with contextlib.suppress(Exception):
                self._execute(client, f"DROP TABLE IF EXISTS `{name}`")

    def test_merge_no_conflict(self, db_client):
        """
        Test merge with no conflicts - new rows are inserted into target.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        current_table = f"test_merge_current_{ts}"
        incoming_table = f"test_merge_incoming_{ts}"

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")

            # Add new row only to incoming (no conflict)
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            count_before = self._get_count(db_client, current_table)
            self._execute(db_client, f"MERGE TABLE `{incoming_table}` INTO `{current_table}` STRATEGY FAIL")

            count_after = self._get_count(db_client, current_table)
            assert count_after == count_before + 1, f"Expected {count_before + 1} rows, got {count_after}"
            print(f"\n✅ Merge no conflict: {count_before} -> {count_after} rows")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)

    def test_merge_strategy_theirs(self, db_client):
        """
        Test merge with THEIRS strategy - incoming values overwrite on conflict.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        current_table = f"test_merge_current_{ts}"
        incoming_table = f"test_merge_theirs_{ts}"

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(
                db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90), (3, 'Charlie', 70)"
            )
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")

            # Modify a row in incoming (creates conflict)
            self._execute(db_client, f"UPDATE `{incoming_table}` SET score = 85 WHERE id = 1")
            # Add a new row in incoming (no conflict)
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (4, 'David', 95)")

            self._execute(db_client, f"MERGE TABLE `{incoming_table}` INTO `{current_table}` STRATEGY THEIRS")

            # Current should have 4 rows now
            assert self._get_count(db_client, current_table) == 4

            # Conflicting row should have incoming's value
            row = self._get_row(db_client, current_table, 1)
            if isinstance(row, dict):
                assert row["score"] == 85, f"Expected score=85 after THEIRS merge, got {row['score']}"
            else:
                assert row[2] == 85, f"Expected score=85 after THEIRS merge, got {row[2]}"
            print("\n✅ Merge THEIRS: conflict resolved with incoming value (score=85)")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)

    def test_merge_strategy_ours(self, db_client):
        """
        Test merge with OURS strategy - current values preserved on conflict.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        current_table = f"test_merge_current_{ts}"
        incoming_table = f"test_merge_ours_{ts}"

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(
                db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90), (3, 'Charlie', 70)"
            )
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")

            # Modify a row in incoming (creates conflict)
            self._execute(db_client, f"UPDATE `{incoming_table}` SET score = 85 WHERE id = 1")
            # Add a new row in incoming (no conflict)
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (4, 'David', 95)")

            self._execute(db_client, f"MERGE TABLE `{incoming_table}` INTO `{current_table}` STRATEGY OURS")

            # Current should have 4 rows (new row inserted)
            assert self._get_count(db_client, current_table) == 4

            # Conflicting row should keep current's value
            row = self._get_row(db_client, current_table, 1)
            if isinstance(row, dict):
                assert row["score"] == 80, f"Expected score=80 after OURS merge, got {row['score']}"
            else:
                assert row[2] == 80, f"Expected score=80 after OURS merge, got {row[2]}"
            print("\n✅ Merge OURS: conflict resolved by keeping current value (score=80)")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)

    def test_merge_strategy_fail_with_conflict(self, db_client):
        """
        Test merge with FAIL strategy raises error when conflicts exist, and rolls back.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        current_table = f"test_merge_current_{ts}"
        incoming_table = f"test_merge_fail_{ts}"

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")

            # Modify a row in incoming to create a conflict
            self._execute(db_client, f"UPDATE `{incoming_table}` SET score = 85 WHERE id = 1")

            # FAIL strategy should raise error on conflict
            with pytest.raises(pymysql.err.OperationalError):
                self._execute(db_client, f"MERGE TABLE `{incoming_table}` INTO `{current_table}` STRATEGY FAIL")

            # Current should be unchanged (transaction rolled back)
            assert self._get_count(db_client, current_table) == 2
            row = self._get_row(db_client, current_table, 1)
            if isinstance(row, dict):
                assert row["score"] == 80, "Current table should be unchanged after FAIL rollback"
            else:
                assert row[2] == 80, "Current table should be unchanged after FAIL rollback"
            print("\n✅ Merge FAIL: correctly raised error on conflict and rolled back")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)

    def test_merge_invalid_strategy(self, db_client):
        """
        Test merge with invalid strategy raises ValueError via Collection API.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        from pyseekdb.client.collection import Collection

        server = db_client._server
        dummy_incoming = Collection(client=server, name="dummy_incoming", collection_id=None)
        dummy_target = Collection(client=server, name="dummy_target", collection_id=None)

        with pytest.raises(ValueError, match="Invalid merge strategy"):
            dummy_incoming.merge_into(dummy_target, strategy="INVALID")

        print("\n✅ Invalid strategy correctly raises ValueError")

    def test_merge_default_strategy(self, db_client):
        """
        Test merge with default strategy (FAIL) - no conflicts should succeed.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        ts = int(time.time() * 1000)
        current_table = f"test_merge_current_{ts}"
        incoming_table = f"test_merge_default_{ts}"

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")

            # Add new row only (no conflict)
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            # Default strategy (no STRATEGY clause = FAIL, but no conflicts so it works)
            self._execute(db_client, f"MERGE TABLE `{incoming_table}` INTO `{current_table}`")

            assert self._get_count(db_client, current_table) == 3
            print("\n✅ Merge with default strategy: 3 rows")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)

    def test_merge_via_collection_api(self, db_client):
        """
        Test merge through the Collection.merge_into() public API.
        """
        if not self._is_diff_merge_enabled(db_client):
            pytest.skip("Diff/Merge is not enabled for this database")

        from pyseekdb.client.collection import Collection
        from pyseekdb.client.meta_info import CollectionNames

        ts = int(time.time() * 1000)
        current_name = f"test_merge_api_current_{ts}"
        incoming_name = f"test_merge_api_incoming_{ts}"
        current_table = CollectionNames.table_name(current_name)
        incoming_table = CollectionNames.table_name(incoming_name)

        try:
            self._execute(
                db_client, f"CREATE TABLE `{current_table}` (id INT PRIMARY KEY, name VARCHAR(50), score INT)"
            )
            self._execute(db_client, f"INSERT INTO `{current_table}` VALUES (1, 'Alice', 80), (2, 'Bob', 90)")
            self._execute(db_client, f"FORK TABLE `{current_table}` TO `{incoming_table}`")
            self._execute(db_client, f"INSERT INTO `{incoming_table}` VALUES (3, 'Charlie', 70)")

            server = db_client._server
            current_col = Collection(client=server, name=current_name, collection_id=None)
            incoming_col = Collection(client=server, name=incoming_name, collection_id=None)

            # Merge via Collection API
            incoming_col.merge_into(current_col, strategy="FAIL")

            count = self._get_count(db_client, current_table)
            assert count == 3, f"Expected 3 rows after merge via API, got {count}"
            print(f"\n✅ Merge via Collection API: {count} rows")
        finally:
            self._cleanup_tables(db_client, incoming_table, current_table)
