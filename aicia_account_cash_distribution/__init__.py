from . import models
from odoo import api, SUPERUSER_ID

# ...existing code...


def _ensure_receiver_analytic(env, company):
	receiver = company.cash_distribution_receiver_analytic_id
	if receiver:
		return receiver
	receiver = env['account.analytic.account'].sudo().search([
		('company_id', '=', company.id),
		('name', 'ilike', 'aicia'),
	], limit=1)
	if receiver:
		company.sudo().write({'cash_distribution_receiver_analytic_id': receiver.id})
		return receiver
	analytic_plan = env['account.analytic.plan'].sudo().search([], limit=1)
	receiver = env['account.analytic.account'].sudo().create({
		'name': 'AICIA - Receptora Distribución',
		'company_id': company.id,
		'plan_id': analytic_plan.id if analytic_plan else False,
	})
	company.sudo().write({'cash_distribution_receiver_analytic_id': receiver.id})
	return receiver


def _ensure_distribution_journal(env, company):
	if company.cash_distribution_journal_id:
		return company.cash_distribution_journal_id
	journal = env['account.journal'].sudo().search([
		('company_id', '=', company.id),
		('type', '=', 'general'),
	], limit=1)
	if journal:
		company.sudo().write({'cash_distribution_journal_id': journal.id})
	return journal


def _create_default_plan(env, company):
	plan_model = env['aicia.distribution.plan'].sudo()
	plan = plan_model.search([
		('company_id', '=', company.id),
		('name', '=', 'Distribución AICIA por defecto'),
	], limit=1)
	plan_model._setup_default_plan(company)
	return plan


def post_init_hook(cr, registry):
	env = api.Environment(cr, SUPERUSER_ID, {})
	for company in env['res.company'].sudo().search([]):
		_ensure_distribution_journal(env, company)
		plan = _create_default_plan(env, company)
		if plan and not company.cash_distribution_active:
			company.sudo().write({'cash_distribution_active': True})



def _table_exists(cr, table_name):
	cr.execute("SELECT to_regclass(%s)", (table_name,))
	return bool(cr.fetchone()[0])


def pre_init_hook(cr_or_env):
	"""Limpia relaciones huérfanas previas al refactor del modelo de log."""
	cr = getattr(cr_or_env, "cr", cr_or_env)
	for table, stmt in (
		(
			"aicia_dist_move_source_analytic_rel",
			"""
			DELETE FROM aicia_dist_move_source_analytic_rel rel
			WHERE NOT EXISTS (
				SELECT 1 FROM account_move am WHERE am.id = rel.distribution_move_id
			)
			""",
		),
		(
			"aicia_dist_move_plan_rel",
			"""
			DELETE FROM aicia_dist_move_plan_rel rel
			WHERE NOT EXISTS (
				SELECT 1 FROM account_move am WHERE am.id = rel.distribution_move_id
			)
			""",
		),
	):
		if not _table_exists(cr, table):
			continue
		cr.execute(stmt)
