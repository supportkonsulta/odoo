import logging
from types import SimpleNamespace

from odoo import models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class CustomPayrollRuleEngine(models.AbstractModel):
    _name = 'custom.payroll.rule.engine'
    _description = 'Salary Rule Engine (helper for executing Python rules)'

    def _build_categories(self, payslip):
        bpjs_total = sum(
            payslip.detail_ids.filtered(lambda d: d.component_type == 'bpjs').mapped('nominal')
        )
        return SimpleNamespace(
            BASIC=payslip.total_gaji_pokok,
            TUNJANGAN=payslip.total_tunjangan,
            LEMBUR=payslip.total_lembur,
            POTONGAN=payslip.total_potongan - bpjs_total,
            BPJS=bpjs_total,
            NET=payslip.total_pendapatan,
        )

    def _build_localdict(self, payslip):
        return {
            'employee': payslip.employee_id,
            'contract': payslip.employee_id.version_id if payslip.employee_id else None,
            'payslip': payslip,
            'categories': self._build_categories(payslip),
            'result': 0.0,
            'True': True,
            'False': False,
            'None': None,
            'round': round,
            'abs': abs,
            'min': min,
            'max': max,
            'sum': sum,
        }

    def _eval_condition(self, expr, localdict):
        try:
            return bool(safe_eval(expr, localdict, mode='eval'))
        except Exception as e:
            _logger.warning('Rule condition eval failed: %s | expr=%s', e, expr)
            return False

    def _eval_amount(self, code, localdict):
        safe_eval(code, localdict, mode='exec')
        return localdict.get('result', 0.0)

    def run_rules(self, payslip, raise_on_error=False):
        rules = self.env['custom.payroll.rule'].search([
            ('company_id', '=', payslip.company_id.id),
            ('active', '=', True),
        ], order='sequence, id')
        results = []
        for rule in rules:
            localdict = self._build_localdict(payslip)
            try:
                if self._eval_condition(rule.condition, localdict):
                    amount = float(self._eval_amount(rule.amount_python, localdict) or 0.0)
                else:
                    amount = 0.0
            except Exception as e:
                _logger.error('Rule %s execution failed: %s', rule.code, e)
                if raise_on_error:
                    raise
                amount = 0.0
            results.append((rule, amount))
        return results
