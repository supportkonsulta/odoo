"""Fix migration: Drop FK constraints and update references.

The previous migration (19.0.2.0.0) failed to update references because
foreign key constraints were still in place. This script:
1. Drops FK constraints from sifnext_ppl, transaksi_transaction, res_users
2. Updates unit_id references from sifnext_unit to hr_department
3. Optionally drops the old sifnext_unit table
"""
import logging

_logger = logging.getLogger(__name__)


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
        _logger.info("sifnext_unit table does not exist, skipping fix migration")
        return

    for table, column in [
        ('sifnext_ppl', 'unit_id'),
        ('transaksi_transaction', 'unit_id'),
        ('res_users', 'unit_id'),
    ]:
        _drop_fk_if_exists(cr, table, column)

    cr.execute("""
        SELECT su.id, hd.id
        FROM sifnext_unit su
        JOIN hr_department hd ON hd.code = su.code AND hd.company_id = su.company_id
    """)
    mappings = cr.fetchall()

    if not mappings:
        _logger.info("No mappings found between sifnext_unit and hr_department")
        return

    id_mapping = {old_id: new_id for old_id, new_id in mappings}
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

    _logger.info("Fix migration complete: %s unit mappings applied", len(id_mapping))

    cr.execute("""
        SELECT su.id, hd.id
        FROM sifnext_unit su
        JOIN hr_department hd ON hd.code = su.code AND hd.company_id = su.company_id
        WHERE su.code = 'UAT'
    """)
    uat_mapping = cr.fetchone()
    if uat_mapping:
        old_unit_id, new_dept_id = uat_mapping
        cr.execute("""
            UPDATE ir_model_data
            SET model = 'hr.department', res_id = %s, module = 'sifnext_ppl', name = 'dept_uat_ppl'
            WHERE model = 'sifnext.unit' AND name = 'unit_uat_ppl' AND module = 'sifnext_ppl'
        """, (new_dept_id,))
        if cr.rowcount == 0:
            cr.execute("""
                INSERT INTO ir_model_data (module, name, model, res_id, noupdate)
                VALUES ('sifnext_ppl', 'dept_uat_ppl', 'hr.department', %s, TRUE)
            """, (new_dept_id,))
        _logger.info("Updated XML ID for UAT department: %s -> %s", old_unit_id, new_dept_id)
