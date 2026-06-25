import base64
from io import BytesIO

import openpyxl

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase


class TestAiciaAccountPgcRecode(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company
        cls.rule_model = cls.env['aicia.account.pgc.recode.rule']

        account_model = cls.env['account.account'].with_company(cls.company)

        cls.account_640 = account_model.create({
            'code': '640000',
            'name': 'Sueldos y Salarios',
            'account_type': 'expense',
        })

        cls.account_old_1 = account_model.create({
            'code': '610000034',
            'name': 'Old Salary 1',
            'account_type': 'expense',
        })

        cls.journal = cls.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', cls.company.id)], limit=1)
        if not cls.journal:
            cls.journal = cls.env['account.journal'].create({
                'name': 'General Test',
                'code': 'GEN',
                'type': 'general',
                'company_id': cls.company.id,
            })

        cls.move = cls.env['account.move'].create({
            'journal_id': cls.journal.id,
            'date': '2026-01-01',
            'line_ids': [
                (0, 0, {'account_id': cls.account_old_1.id, 'debit': 100.0, 'credit': 0.0, 'name': 'Test line 1'}),
                (0, 0, {'account_id': cls.account_640.id, 'debit': 0.0, 'credit': 100.0, 'name': 'Test line 2'})
            ]
        })
        cls.move.action_post()

    def setUp(self):
        super().setUp()
        self.rule_model.search([('company_id', '=', self.company.id)]).unlink()

    def _ensure_account(self, code, name='Cuenta de prueba'):
        account_model = self.env['account.account'].with_company(self.company)
        account = account_model.search([
            ('company_ids', '=', self.company.id),
            ('code', '=', code),
        ], limit=1)
        if not account:
            account = account_model.create({
                'code': code,
                'name': name,
                'account_type': 'expense',
            })
        return account

    @staticmethod
    def _build_aicia_excel(rows):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'Hoja1'
        sheet['A1'] = 'LISTADO DE SALDOS DEL PLAN GENERAL ORDENADO POR CUENTAS - EJERCICIO 2025'
        sheet['A4'] = 'Cuenta PGC'
        sheet['B4'] = ' Cuenta                 AICIA                             '
        for row_number, row_values in enumerate(rows, start=5):
            for column_number, value in enumerate(row_values, start=1):
                sheet.cell(row=row_number, column=column_number, value=value)

        output = BytesIO()
        workbook.save(output)
        return output.getvalue()

    def test_01_rule_creation_and_computation(self):
        self._ensure_account('640034', 'Sueldos y salarios 034')

        rule = self.env['aicia.account.pgc.recode.rule'].create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })
        self.assertEqual(rule.proposed_code, '640034')

    def test_02_load_default_rules_from_bundled_excel(self):
        self._ensure_account('100000', 'Capital social')
        self._ensure_account('628100', 'Teléfono')

        template_path = self.rule_model._get_default_rules_template_path()
        self.assertTrue(template_path.exists())

        template_rows = self.rule_model.parse_rules_template_file(template_path.read_bytes())
        self.assertGreaterEqual(len(template_rows), 1500)
        self.assertEqual(template_rows[0]['old_code'], '100000000')
        self.assertEqual(template_rows[0]['target_prefix'], '100')

        loaded_rules = self.rule_model.load_default_rules_for_company(self.company)
        first_count = self.rule_model.search_count([
            ('company_id', '=', self.company.id),
            ('is_default_data', '=', True),
        ])

        self.assertGreaterEqual(len(loaded_rules), 1500)
        self.assertGreaterEqual(first_count, 1500)

        capital_rule = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '100000000'),
        ], limit=1)
        self.assertEqual(capital_rule.target_prefix, '100')
        self.assertEqual(capital_rule.target_label, 'CAPITAL SOCIAL')
        self.assertEqual(capital_rule.proposed_code, '100000')
        self.assertEqual(capital_rule.status, 'automatic')
        self.assertTrue(capital_rule.is_default_data)

        manual_rule = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '116000000'),
        ], limit=1)
        self.assertEqual(manual_rule.target_prefix, '116/117')
        self.assertEqual(manual_rule.status, 'manual')

        inherited_rule = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '642000100'),
        ], limit=1)
        self.assertEqual(inherited_rule.target_prefix, '628')
        self.assertEqual(inherited_rule.proposed_code, '628100')
        self.assertEqual(inherited_rule.status, 'automatic')

        self.rule_model.load_default_rules_for_company(self.company)
        second_count = self.rule_model.search_count([
            ('company_id', '=', self.company.id),
            ('is_default_data', '=', True),
        ])
        self.assertEqual(first_count, second_count)

    def test_03_import_wizard_accepts_ooxml_xls_and_continuations(self):
        self._ensure_account('640036', 'Gastos de personal 036')

        file_content = self._build_aicia_excel([
            ('640 GASTOS DE PERSONAL', '610000034 Persona 1'),
            ('"', '610000035 Persona 2'),
            ('', '610000036 Persona 3'),
            ('116/117 RESERVAS ESTATUTARIAS/VOLUNTARIAS', '116000000 Reserva'),
            ('CIERRE PROYECTOS', '130'),
            ('', 'TOTAL CUENTAS NIVEL 9 .....'),
        ])

        wizard = self.env['aicia.account.pgc.recode.import.wizard'].create({
            'company_id': self.company.id,
            'file': base64.b64encode(file_content),
            'filename': 'reglas.xls',
            'clear_existing_rules': True,
        })
        wizard.action_import()

        imported_rules = self.rule_model.search([
            ('company_id', '=', self.company.id),
        ], order='old_code')
        self.assertEqual(len(imported_rules), 5)

        inherited_quote = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '610000035'),
        ], limit=1)
        self.assertEqual(inherited_quote.target_prefix, '640')
        self.assertEqual(inherited_quote.target_label, 'GASTOS DE PERSONAL')
        self.assertEqual(inherited_quote.old_name, 'Persona 2')

        inherited_blank = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '610000036'),
        ], limit=1)
        self.assertEqual(inherited_blank.target_prefix, '640')
        self.assertEqual(inherited_blank.proposed_code, '640036')
        self.assertEqual(inherited_blank.status, 'automatic')

        slash_rule = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '116000000'),
        ], limit=1)
        self.assertEqual(slash_rule.status, 'manual')

        closure_rule = self.rule_model.search([
            ('company_id', '=', self.company.id),
            ('old_code', '=', '130'),
        ], limit=1)
        self.assertEqual(closure_rule.status, 'manual')

    def test_04_simulation_and_apply(self):
        self._ensure_account('640034', 'Sueldos y salarios 034')

        self.env['aicia.account.pgc.recode.rule'].create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        wizard = self.env['aicia.account.pgc.recode.simulation.wizard'].create({
            'company_id': self.company.id,
        })
        res = wizard.action_simulate()
        batch_id = res['res_id']
        batch = self.env['aicia.account.pgc.recode.batch'].browse(batch_id)

        self.assertTrue(batch.move_line_count >= 1)

        apply_wiz = self.env['aicia.account.pgc.recode.apply.wizard'].create({
            'batch_id': batch.id,
            'apply_automatic': True,
            'create_missing_accounts': True,
        })
        apply_wiz.action_apply()

        recode_line = batch.line_ids.filtered(lambda l: l.old_account_id == self.account_old_1)
        self.assertTrue(recode_line.applied)
        self.assertEqual(recode_line.new_account_id.code, '640034')

        move_line = recode_line.move_line_id
        self.assertEqual(move_line.account_id.code, '640034')
        self.assertTrue(move_line.aicia_pgc_recode_applied)

        batch.action_revert()
        self.assertFalse(recode_line.applied)
        self.assertEqual(move_line.account_id, self.account_old_1)

    def test_05_list_views_load_currency_for_monetary_aggregates(self):
        line_tree_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_line_tree'
        )
        batch_form_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_batch_form'
        )

        self.assertIn('name="company_currency_id"', line_tree_view.arch_db)
        self.assertIn('create="false"', line_tree_view.arch_db)
        self.assertIn('sum="Total debe"', line_tree_view.arch_db)
        self.assertIn('name="company_currency_id"', batch_form_view.arch_db)
        self.assertIn('sum="Total debe"', batch_form_view.arch_db)

    def test_06_main_actions_and_views_are_in_spanish(self):
        rule_action = self.env.ref('aicia_account_pgc_recode.action_aicia_account_pgc_recode_rule')
        import_action = self.env.ref('aicia_account_pgc_recode.action_aicia_account_pgc_recode_import_wizard')
        simulation_action = self.env.ref('aicia_account_pgc_recode.action_aicia_account_pgc_recode_simulation_wizard')
        rule_form_view = self.env.ref('aicia_account_pgc_recode.view_aicia_account_pgc_recode_rule_form')
        apply_wizard_view = self.env.ref('aicia_account_pgc_recode.view_aicia_account_pgc_recode_apply_wizard_form')

        self.assertEqual(rule_action.name, 'Reglas de recodificación')
        self.assertEqual(import_action.name, 'Importar equivalencias')
        self.assertEqual(simulation_action.name, 'Recodificación por mapeo')
        self.assertIn('Marcar como automática', rule_form_view.arch_db)
        self.assertIn('Colisión detectada', rule_form_view.arch_db)
        self.assertIn('Aplicar lote de recodificación', apply_wizard_view.arch_db)
        self.assertIn('Esta acción modificará los apuntes contables', apply_wizard_view.arch_db)

    def test_07_proposed_code_can_be_overridden_manually(self):
        self._ensure_account('641999', 'Cuenta propuesta manual')

        rule = self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        rule.proposed_code = '641999'

        self.assertEqual(rule.target_prefix, '641999')
        self.assertEqual(rule.proposed_code, '641999')
        self.assertEqual(rule.status, 'automatic')

    def test_07b_proposed_code_requires_existing_account(self):
        rule = self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        with self.assertRaisesRegex(
            ValidationError,
            'La cuenta propuesta debe existir previamente',
        ):
            rule.proposed_code = '641998'

    def test_07c_proposed_account_can_be_selected_manually(self):
        target_account = self._ensure_account('642222', 'Cuenta propuesta desde many2one')

        rule = self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        rule.proposed_account_id = target_account

        self.assertEqual(rule.target_prefix, '642222')
        self.assertEqual(rule.proposed_code, '642222')
        self.assertEqual(rule.proposed_account_id, target_account)
        self.assertEqual(rule.status, 'automatic')

    def test_08_rule_and_batch_views_allow_manual_adjustments(self):
        rule_tree_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_rule_tree'
        )
        line_tree_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_line_tree'
        )
        batch_form_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_batch_form'
        )
        simulation_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_simulation_wizard_form'
        )

        move_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_move_wizard_form'
        )

        self.assertIn('editable="bottom"', rule_tree_view.arch_db)
        self.assertIn('create="false"', rule_tree_view.arch_db)
        self.assertIn('name="proposed_account_id"', rule_tree_view.arch_db)
        self.assertIn("name=\"target_label\" optional=\"hide\"", rule_tree_view.arch_db)
        self.assertIn("status not in ('review', 'manual')", line_tree_view.arch_db)
        self.assertIn('name="line_ids"', batch_form_view.arch_db)
        self.assertIn('name="new_account_id"', batch_form_view.arch_db)
        self.assertIn('editable="bottom"', batch_form_view.arch_db)
        self.assertIn('name="journal_ids"', simulation_view.arch_db)
        self.assertIn('name="source_account_id"', move_view.arch_db)
        self.assertIn('name="target_account_id"', move_view.arch_db)

    def test_09_manual_edit_recomputes_status_and_collision(self):
        self._ensure_account('640034', 'Cuenta 640034')
        self._ensure_account('640134', 'Cuenta 640134')
        self._ensure_account('641134', 'Cuenta 641134')
        self._ensure_account('116999', 'Cuenta 116999')

        first_rule = self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })
        second_rule = self.rule_model.create({
            'old_code': '610000134',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        self.assertEqual(first_rule.status, 'automatic')
        self.assertEqual(second_rule.status, 'automatic')

        second_rule.proposed_code = first_rule.proposed_code
        first_rule.invalidate_recordset()
        second_rule.invalidate_recordset()

        self.assertTrue(first_rule.collision)
        self.assertTrue(second_rule.collision)
        self.assertEqual(first_rule.status, 'review')
        self.assertEqual(second_rule.status, 'review')

        second_rule.proposed_code = '641134'
        first_rule.invalidate_recordset()
        second_rule.invalidate_recordset()

        self.assertFalse(first_rule.collision)
        self.assertFalse(second_rule.collision)
        self.assertEqual(first_rule.status, 'automatic')
        self.assertEqual(second_rule.status, 'automatic')

        manual_rule = self.rule_model.create({
            'old_code': '116000000',
            'target_prefix': '116/117',
            'company_id': self.company.id,
            'status': 'manual',
        })
        self.assertEqual(manual_rule.status, 'manual')

        manual_rule.proposed_code = '116999'

        self.assertEqual(manual_rule.target_prefix, '116999')
        self.assertEqual(manual_rule.proposed_code, '116999')
        self.assertEqual(manual_rule.status, 'automatic')

    def test_10_rule_requires_existing_exact_subaccount(self):
        rule = self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        self.assertEqual(rule.proposed_code, '640034')
        self.assertFalse(rule.proposed_account_id)
        self.assertEqual(rule.status, 'manual')

        with self.assertRaisesRegex(
            ValidationError,
            'La subcuenta propuesta debe existir previamente',
        ):
            rule.write({'status': 'review'})

        with self.assertRaisesRegex(
            ValidationError,
            'La subcuenta propuesta debe existir previamente',
        ):
            rule.write({'status': 'automatic'})

        with self.assertRaisesRegex(
            ValidationError,
            'La subcuenta propuesta debe existir previamente',
        ):
            rule.action_mark_automatic()

        self.assertEqual(rule.status, 'manual')

        wizard = self.env['aicia.account.pgc.recode.simulation.wizard'].create({
            'company_id': self.company.id,
        })
        res = wizard.action_simulate()
        batch = self.env['aicia.account.pgc.recode.batch'].browse(res['res_id'])
        recode_line = batch.line_ids.filtered(lambda line: line.old_account_id == self.account_old_1)

        self.assertEqual(recode_line.status, 'manual')
        self.assertEqual(
            recode_line.blocking_reason,
            'La subcuenta propuesta no existe en el plan contable de la compañía.',
        )

        self._ensure_account('640034', 'Sueldos y salarios 034')
        rule._recompute_collision_and_status(rule.company_id)

        self.assertTrue(rule._find_proposed_account())
        self.assertEqual(rule.status, 'automatic')

        rule.action_mark_manual()
        self.assertEqual(rule.status, 'manual')
        rule.action_mark_automatic()
        self.assertEqual(rule.status, 'automatic')

    def test_11_blocking_reason_is_computed(self):
        batch = self.env['aicia.account.pgc.recode.batch'].create({
            'company_id': self.company.id,
            'state': 'simulated',
        })
        move_line = self.move.line_ids[0]

        manual_line = self.env['aicia.account.pgc.recode.line'].create({
            'batch_id': batch.id,
            'move_line_id': move_line.id,
            'old_account_id': self.account_old_1.id,
            'status': 'manual',
            'notes': 'Requiere validación manual.',
        })
        review_line = self.env['aicia.account.pgc.recode.line'].create({
            'batch_id': batch.id,
            'move_line_id': move_line.id,
            'old_account_id': self.account_old_1.id,
            'status': 'review',
            'notes': 'Colisiona con: 610000999',
        })
        error_line = self.env['aicia.account.pgc.recode.line'].create({
            'batch_id': batch.id,
            'move_line_id': move_line.id,
            'old_account_id': self.account_old_1.id,
            'status': 'error',
            'notes': 'No se ha definido ninguna cuenta destino.',
        })
        reverted_line = self.env['aicia.account.pgc.recode.line'].create({
            'batch_id': batch.id,
            'move_line_id': move_line.id,
            'old_account_id': self.account_old_1.id,
            'status': 'review',
            'notes': 'Pendiente de revisión.',
            'reverted': True,
        })

        self.assertEqual(manual_line.blocking_reason, 'Requiere validación manual.')
        self.assertEqual(review_line.blocking_reason, 'Colisiona con: 610000999')
        self.assertEqual(error_line.blocking_reason, 'No se ha definido ninguna cuenta destino.')
        self.assertEqual(
            reverted_line.blocking_reason,
            'Línea revertida; revisa la propuesta antes de volver a aplicarla.',
        )

    def test_12_views_show_blocking_reason(self):
        line_tree_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_line_tree'
        )
        batch_form_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_batch_form'
        )

        self.assertIn('name="blocking_reason"', line_tree_view.arch_db)
        self.assertIn('name="blocking_reason"', batch_form_view.arch_db)

    def test_13_move_wizard_applies_account_change_directly(self):
        target_account = self._ensure_account('642222', 'Cuenta destino puntual')

        wizard = self.env['aicia.account.pgc.recode.move.wizard'].create({
            'company_id': self.company.id,
            'source_account_id': self.account_old_1.id,
            'target_account_id': target_account.id,
        })

        self.assertEqual(wizard.move_line_count, 1)

        result = wizard.action_apply_move()

        self.assertEqual(result['tag'], 'display_notification')
        move_line = self.move.line_ids.filtered(
            lambda line: line.name == 'Test line 1'
        )
        self.assertEqual(move_line.account_id, target_account)
        self.assertTrue(move_line.aicia_pgc_recode_applied)
        self.assertEqual(move_line.aicia_pgc_recode_original_account_id, self.account_old_1)
        self.assertFalse(move_line.aicia_pgc_recode_last_batch_id)

    def test_13b_move_wizard_filters_by_date_range(self):
        target_account = self._ensure_account('642223', 'Cuenta destino por fecha')
        later_move = self.env['account.move'].create({
            'journal_id': self.journal.id,
            'date': '2026-03-15',
            'line_ids': [
                (0, 0, {
                    'account_id': self.account_old_1.id,
                    'debit': 70.0,
                    'credit': 0.0,
                    'name': 'Out of range line',
                }),
                (0, 0, {
                    'account_id': self.account_640.id,
                    'debit': 0.0,
                    'credit': 70.0,
                    'name': 'Out of range counterpart',
                }),
            ],
        })
        later_move.action_post()

        wizard = self.env['aicia.account.pgc.recode.move.wizard'].create({
            'company_id': self.company.id,
            'source_account_id': self.account_old_1.id,
            'target_account_id': target_account.id,
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })

        self.assertEqual(wizard.move_line_count, 1)
        wizard.action_apply_move()

        in_range_line = self.move.line_ids.filtered(lambda line: line.name == 'Test line 1')
        out_range_line = later_move.line_ids.filtered(lambda line: line.name == 'Out of range line')
        self.assertEqual(in_range_line.account_id, target_account)
        self.assertEqual(out_range_line.account_id, self.account_old_1)

    def test_13c_move_wizard_rejects_invalid_configuration(self):
        target_account = self._ensure_account('642224', 'Cuenta destino inválida')

        same_account_wizard = self.env['aicia.account.pgc.recode.move.wizard'].create({
            'company_id': self.company.id,
            'source_account_id': self.account_old_1.id,
            'target_account_id': self.account_old_1.id,
        })
        with self.assertRaises(ValidationError):
            same_account_wizard.action_apply_move()

        bad_dates_wizard = self.env['aicia.account.pgc.recode.move.wizard'].create({
            'company_id': self.company.id,
            'source_account_id': self.account_old_1.id,
            'target_account_id': target_account.id,
            'date_from': '2026-02-01',
            'date_to': '2026-01-01',
        })
        with self.assertRaises(ValidationError):
            bad_dates_wizard.action_apply_move()

    def test_13d_move_wizard_requires_matching_move_lines(self):
        target_account = self._ensure_account('642225', 'Cuenta destino sin apuntes')
        empty_account = self._ensure_account('612999', 'Cuenta sin movimientos')

        wizard = self.env['aicia.account.pgc.recode.move.wizard'].create({
            'company_id': self.company.id,
            'source_account_id': empty_account.id,
            'target_account_id': target_account.id,
        })

        self.assertEqual(wizard.move_line_count, 0)
        with self.assertRaises(UserError):
            wizard.action_apply_move()

    def test_13e_move_wizard_menu_and_action_exist(self):
        move_action = self.env.ref(
            'aicia_account_pgc_recode.action_aicia_account_pgc_recode_move_wizard'
        )
        move_menu = self.env.ref(
            'aicia_account_pgc_recode.menu_aicia_account_pgc_recode_move'
        )

        self.assertEqual(move_action.name, 'Mover cuenta a cuenta')
        self.assertEqual(move_menu.action, move_action)

    def test_14_secondary_menus_are_hidden_by_default(self):
        batch_menu = self.env.ref('aicia_account_pgc_recode.menu_aicia_account_pgc_recode_batches')
        line_menu = self.env.ref('aicia_account_pgc_recode.menu_aicia_account_pgc_recode_lines')

        self.assertFalse(batch_menu.active)
        self.assertFalse(line_menu.active)

    def test_15_preview_builds_subaccount_mapping(self):
        target = self._ensure_account('640034', 'Sueldos y salarios 034')
        self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        wizard = self.env['aicia.account.pgc.recode.simulation.wizard'].create({
            'company_id': self.company.id,
        })
        wizard.action_preview()

        self.assertTrue(wizard.preview_generated)

        old_preview = wizard.preview_line_ids.filtered(
            lambda line: line.old_account_id == self.account_old_1
        )
        self.assertEqual(len(old_preview), 1)
        self.assertEqual(old_preview.new_account_id, target)
        self.assertEqual(old_preview.status, 'automatic')
        self.assertEqual(old_preview.move_line_count, 1)
        self.assertEqual(old_preview.total_balance, 100.0)

        discarded_preview = wizard.preview_line_ids.filtered(
            lambda line: line.old_account_id == self.account_640
        )
        self.assertEqual(discarded_preview.status, 'discarded')
        self.assertFalse(discarded_preview.new_account_id)

    def test_16_preview_override_changes_generated_batch(self):
        self._ensure_account('640034', 'Sueldos y salarios 034')
        override_account = self._ensure_account('641999', 'Cuenta override')
        self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        wizard = self.env['aicia.account.pgc.recode.simulation.wizard'].create({
            'company_id': self.company.id,
        })
        wizard.action_preview()
        preview = wizard.preview_line_ids.filtered(
            lambda line: line.old_account_id == self.account_old_1
        )
        preview.new_account_id = override_account

        res = wizard.action_simulate()
        batch = self.env['aicia.account.pgc.recode.batch'].browse(res['res_id'])
        recode_line = batch.line_ids.filtered(
            lambda line: line.old_account_id == self.account_old_1
        )
        self.assertEqual(recode_line.new_account_id, override_account)
        self.assertEqual(recode_line.new_account_code, '641999')
        self.assertEqual(recode_line.status, 'automatic')

    def test_17_preview_without_target_marks_line_manual(self):
        self._ensure_account('640034', 'Sueldos y salarios 034')
        self.rule_model.create({
            'old_code': '610000034',
            'target_prefix': '640',
            'company_id': self.company.id,
        })

        wizard = self.env['aicia.account.pgc.recode.simulation.wizard'].create({
            'company_id': self.company.id,
        })
        wizard.action_preview()
        preview = wizard.preview_line_ids.filtered(
            lambda line: line.old_account_id == self.account_old_1
        )
        preview.new_account_id = False

        res = wizard.action_simulate()
        batch = self.env['aicia.account.pgc.recode.batch'].browse(res['res_id'])
        recode_line = batch.line_ids.filtered(
            lambda line: line.old_account_id == self.account_old_1
        )
        self.assertFalse(recode_line.new_account_id)
        self.assertEqual(recode_line.status, 'manual')

    def test_18_simulation_view_has_mapping_preview_tab(self):
        simulation_view = self.env.ref(
            'aicia_account_pgc_recode.view_aicia_account_pgc_recode_simulation_wizard_form'
        )

        self.assertIn('name="preview_line_ids"', simulation_view.arch_db)
        self.assertIn('name="action_preview"', simulation_view.arch_db)
        self.assertIn('Mapeo de subcuentas', simulation_view.arch_db)

