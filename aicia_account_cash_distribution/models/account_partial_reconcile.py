from odoo import models, fields, api, _
from odoo.exceptions import UserError

class AccountPartialReconcile(models.Model):
    _inherit = 'account.partial.reconcile'

    distribution_move_ids = fields.One2many(
        'aicia.distribution.move',
        'partial_reconcile_id',
        string='Distribution Moves'
    )

    @api.model
    def create(self, vals):
        reconciles = super().create(vals)
        for rec in reconciles:
            rec._process_cash_distribution()
        return reconciles

    def unlink(self):
        # Reverse moves before unlinking
        for rec in self:
            rec._reverse_cash_distribution()
        return super().unlink()

    def _process_cash_distribution(self):
        """
        Main logic to distribute cash based on reconciliation.
        """
        for rec in self:
            # Check if active
            if not rec.company_id.cash_distribution_active:
                continue

            # Identify Invoice and Payment
            invoice_move = None

            # Check moves. Typically one is invoice, one is payment.
            # We want to catch when an invoice is being paid.
            # Invoice is usually the one with move_type out_invoice/out_refund

            moves = [rec.debit_move_id.move_id, rec.credit_move_id.move_id]
            invoice_move = next((m for m in moves if m.move_type in ('out_invoice', 'out_refund')), None)

            if not invoice_move:
                continue

            # Skip if not posted (should be posted though)
            if invoice_move.state != 'posted':
                continue

            # Calculate ratio
            # Use company currency amount for ratio to be safe
            # total_amount = invoice_amount_total_signed (in company currency)
            # rec_amount = rec.amount (in company currency)

            total_amount = abs(invoice_move.amount_total_signed)
            if total_amount == 0:
                continue

            rec_amount = rec.amount
            if rec_amount == 0:
                continue

            if rec_amount > total_amount:
                 # Edge case: payment larger than invoice (e.g. currency diffs or overpayment)?
                 # Or just float rounding. Clamp to 1.0?
                 # Partial reconcile amount shouldn't exceed open amount, but total_amount is ORIGINAL total.
                 pass

            ratio = rec_amount / total_amount

            # Process lines
            move_lines_vals = []

            # Check for Header Analytic Distribution (Priority)
            header_analytic = getattr(invoice_move, 'analytic_distribution', None)
            if header_analytic:
                # Distribute the full reconciled amount based on header
                base_amount_for_dist = rec.amount # Company Currency

                for account_id_str, percentage in header_analytic.items():
                    if not percentage:
                        continue

                    try:
                        analytic_account_id = int(account_id_str.split(',')[0])
                    except (ValueError, IndexError):
                        continue

                    dist_amount = base_amount_for_dist * (percentage / 100.0)
                    move_lines_vals += self._prepare_distribution_lines(
                        rec, invoice_move, analytic_account_id, dist_amount
                    )
            else:
                # Iterate invoice lines to find analytic distribution
                for line in invoice_move.invoice_line_ids:
                    if line.display_type in ('line_section', 'line_note'):
                        continue

                    # Base amount for this line (in company currency)
                    line_base_amount = abs(line.balance) * ratio

                    if line_base_amount == 0:
                        continue

                    # Get analytic distribution
                    if not line.analytic_distribution:
                       continue

                    # Apply logic for each analytic account in distribution
                    for account_id_str, percentage in line.analytic_distribution.items():
                        if not percentage:
                            continue

                        try:
                            analytic_account_id = int(account_id_str.split(',')[0])
                        except (ValueError, IndexError):
                            continue

                        # Amount of this line belonging to this analytic account
                        dist_amount = line_base_amount * (percentage / 100.0)

                        move_lines_vals += self._prepare_distribution_lines(
                            rec, invoice_move, analytic_account_id, dist_amount
                        )

            if not move_lines_vals:
                continue

            # Create Move
            journal = rec.company_id.cash_distribution_journal_id
            if not journal:
                 # Fallback
                 journal = self.env['account.journal'].search([('type', '=', 'general'), ('company_id', '=', rec.company_id.id)], limit=1)

            if not journal:
                continue # Cannot create move without journal

            move_vals = {
                'move_type': 'entry',
                'journal_id': journal.id,
                'date': rec.max_date,
                'ref': f'Distribution for {invoice_move.name}',
                'line_ids': [(0, 0, vals) for vals in move_lines_vals],
            }

            move = self.env['account.move'].create(move_vals)
            move.action_post()

            # Log
            self.env['aicia.distribution.move'].create({
                'partial_reconcile_id': rec.id,
                'move_id': move.id,
                'amount_total': move.amount_total,
            })

    def _reverse_cash_distribution(self):
        for rec in self:
            for dist_move in rec.distribution_move_ids:
                if dist_move.move_id.state == 'posted':
                    dist_move.move_id.button_draft()
                    dist_move.move_id.button_cancel()
                # unlink log?
                dist_move.unlink()

    def _prepare_distribution_lines(self, rec, invoice_move, analytic_account_id, dist_amount):
        """
        Helper to calculate distribution lines for a specific analytic account and amount.
        """
        lines = []

        # Search Rules
        # Rule Type A: Source Account matches
        rules = self.env['aicia.distribution.rule'].search([
            ('company_id', '=', rec.company_id.id),
            ('active', '=', True),
        ])

        currency = rec.company_id.currency_id

        for rule in rules:
            # Check Source Account Filter
            if rule.source_analytic_account_ids and analytic_account_id not in rule.source_analytic_account_ids.ids:
                continue

            # Calculate final distribution amount
            final_amount = dist_amount * (rule.percentage / 100.0)
            final_amount = currency.round(final_amount)

            if final_amount == 0:
                continue

            # Prepare move lines
            # 1. DEBIT (Source/Expense side)
            lines.append({
                'name': f'Distr: {invoice_move.name} - {rule.name}',
                'account_id': rule.debit_account_id.id,
                'debit': final_amount,
                'credit': 0.0,
                'analytic_distribution': {str(analytic_account_id): 100},
                'partner_id': invoice_move.partner_id.id,
            })

            # 2. CREDIT (Destination/Income side)
            credit_analytic = {}
            if rule.destination_analytic_account_id:
                    credit_analytic = {str(rule.destination_analytic_account_id.id): 100}

            lines.append({
                'name': f'Distr: {invoice_move.name} - {rule.name}',
                'account_id': rule.credit_account_id.id,
                'debit': 0.0,
                'credit': final_amount,
                'analytic_distribution': credit_analytic,
                'partner_id': invoice_move.partner_id.id,
            })

        return lines
