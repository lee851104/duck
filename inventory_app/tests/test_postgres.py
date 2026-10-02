"""Portable SQL contracts; real database tests opt in with TEST_POSTGRES_URL."""
import importlib
import sqlite3
import unittest
from unittest.mock import Mock, patch


class PostgresContractTest(unittest.TestCase):
    def backend(self):
        self.assertIsNotNone(importlib.util.find_spec('app.postgres'),
                             'PostgreSQL backend is required')
        return importlib.import_module('app.postgres')

    def test_parameters_never_replace_quoted_text_or_become_sql(self):
        module = self.backend()
        sql, args = module.bind_sql("SELECT '?' AS literal, ? AS value, '50%' AS pct -- ?\n", ("x'); DROP TABLE products;--",))
        self.assertEqual(sql, "SELECT '?' AS literal, %s AS value, '50%%' AS pct -- ?\n")
        self.assertEqual(args, ("x'); DROP TABLE products;--",))

    def test_named_parameters_repeated_and_cast_colons(self):
        sql, args = self.backend().bind_sql('SELECT :name, :name, 1::text', {'name': '鴨'})
        self.assertEqual(sql, 'SELECT %(name)s, %(name)s, 1::text')
        self.assertEqual(args, {'name': '鴨'})

    def test_mismatched_parameters_and_unsupported_sql_fail_closed(self):
        module = self.backend()
        for sql, args in [('SELECT ?', ()), ('SELECT :missing', {}),
                          ('SELECT ?; DROP TABLE products', (1,)),
                          ('PRAGMA table_info(products)', ()),
                          ('INSERT OR REPLACE INTO metadata VALUES(?,?)', ('a', 'b'))]:
            with self.subTest(sql=sql), self.assertRaises(sqlite3.ProgrammingError):
                module.bind_sql(sql, args)

    def test_row_supports_dict_numeric_access_and_null(self):
        row = self.backend().Row(('id', 'quantity'), (7, None))
        self.assertEqual(row[0], 7)
        self.assertIsNone(row['quantity'])
        self.assertEqual(dict(row), {'id': 7, 'quantity': None})
        self.assertEqual(tuple(row), (7, None))

    def test_schema_identifier_cannot_escape_private_schema(self):
        module = self.backend()
        for schema in ['public', 'auth', 'storage', 'duck; DROP SCHEMA duck', 'a.b', '']:
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                module.validate_schema(schema)
        self.assertEqual(module.validate_schema('duck_qa_123'), 'duck_qa_123')

    def test_driver_failure_details_are_not_exposed_to_http_error_handlers(self):
        import psycopg
        from app.db import connect_db
        with patch('psycopg.connect', side_effect=psycopg.OperationalError('sensitive password and host')):
            with self.assertRaises(sqlite3.OperationalError) as raised:
                connect_db('postgresql://test-placeholder')
        self.assertEqual(str(raised.exception), 'PostgreSQL connection failed')
        self.assertTrue(raised.exception.__suppress_context__)

    def test_rollback_failure_is_sanitized_after_connection_loss(self):
        import psycopg
        from app.db import connect_db
        driver_connection = Mock()
        driver_connection.rollback.side_effect = psycopg.OperationalError('private server information')
        with patch('psycopg.connect', return_value=driver_connection):
            conn = connect_db('postgresql://test-placeholder')
        with self.assertRaises(sqlite3.OperationalError) as raised:
            conn.rollback()
        self.assertEqual(str(raised.exception), 'PostgreSQL rollback failed')
        self.assertTrue(raised.exception.__suppress_context__)


if __name__ == '__main__':
    unittest.main()
