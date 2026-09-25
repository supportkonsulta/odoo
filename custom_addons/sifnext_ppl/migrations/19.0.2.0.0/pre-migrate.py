"""Migrate sifnext.unit data to hr.department.

This pre-migration script runs before the module update, so the sifnext_unit
table still exists AND the new columns on hr_department don't exist yet.
It:
1. Adds the new columns to hr_department if they don't exist
2. Creates hr.department records from sifnext.unit records
3. Updates all FK references in related tables
"""
import json
import logging

_logger = logging.getLogger(__name__)


def _column_exists(cr, table, column):
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = %s AND column_name = %s
        )
    """, (table, column))
    return cr.fetchone()[0]


def _to_jsonb(value):
    return json.dumps({"en_US": value})


def _table_exists(cr, table):
    cr.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = %s
        )
    """, (table,))
    return cr.fetchone()[0]


def _drop_fk_if_exists(cr, table, column):
    if not _table_exists(cr, table):
        return
    
    cr.execute("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = %s
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name LIKE %s
    """, (table, f'{table}_{column}_%'))
    
    constraints = cr.fetchall()
    for (constraint_name,) in constraints:
        cr.execute(f'ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint_name}')
        _logger.info("Dropped FK constraint %s from %s.%s", constraint_name, table, column)


def migrate(cr, version):
    if not version:
        return

    cr.execute("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'sifnext_unit')")
    if not cr.fetchone()[0]:
        _logger.info("sifnext_unit table does not exist, skipping migration")
        return

    for table, column in [
        ('sifnext_ppl', 'unit_id'),
        ('transaksi_transaction', 'unit_id'),
        ('res_users', 'unit_id'),
    ]:
        _drop_fk_if_exists(cr, table, column)

    if not _column_exists(cr, 'hr_department', 'code'):
        cr.execute("ALTER TABLE hr_department ADD COLUMN code VARCHAR")
        _logger.info("Added code column to hr_department")

    if not _column_exists(cr, 'hr_department', 'journal_unit_dept'):
        cr.execute("ALTER TABLE hr_department ADD COLUMN journal_unit_dept VARCHAR DEFAULT 'pusat'")
        _logger.info("Added journal_unit_dept column to hr_department")

    cr.execute("SELECT id, name, code, active, company_id, journal_unit_dept FROM sifnext_unit")
    units = cr.fetchall()

    if not units:
        _logger.info("No sifnext.unit records to migrate")
        return

    id_mapping = {}
    for unit_id, name, code, active, company_id, journal_unit_dept in units:
        if not name or not company_id:
            continue

        name_jsonb = _to_jsonb(name)

        cr.execute("""
            INSERT INTO hr_department (name, code, active, company_id, journal_unit_dept, create_uid, create_date, write_uid, write_date)
            VALUES (%s::jsonb, %s, %s, %s, %s, 1, NOW() AT TIME ZONE 'UTC', 1, NOW() AT TIME ZONE 'UTC')
            RETURNING id
        """, (name_jsonb, code, active if active is not None else True, company_id, journal_unit_dept or 'pusat'))
        new_dept_id = cr.fetchone()[0]
        id_mapping[unit_id] = new_dept_id
        _logger.info("Migrated sifnext.unit %s -> hr.department %s (%s)", unit_id, new_dept_id, name)

    if not id_mapping:
        return

    old_ids = list(id_mapping.keys())

    for table, column in [
        ('sifnext_ppl', 'unit_id'),
        ('transaksi_transaction', 'unit_id'),
        ('res_users', 'unit_id'),
    ]:
        if not _table_exists(cr, table):
            _logger.info("Table %s does not exist, skipping", table)
            continue
        
        case_parts = []
        for old_id, new_id in id_mapping.items():
            case_parts.append(f"WHEN {column} = {old_id} THEN {new_id}")
        case_sql = " ".join(case_parts)

        cr.execute(f"""
            UPDATE {table}
            SET {column} = CASE {case_sql} ELSE {column} END
            WHERE {column} IN %s
        """, (tuple(old_ids),))
        _logger.info("Updated %s %s records", cr.rowcount, table)

    _logger.info("Migration complete: %s units migrated", len(id_mapping))
