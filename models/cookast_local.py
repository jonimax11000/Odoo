# -*- coding: utf-8 -*-
# models/cookast_local.py
# Modelo central de Gestión Multilocal Cookast.
# Representa un local/sucursal de la franquicia (ej: "HUNDRED El Palmar").
# Al crear un local, se auto-crea un stock.warehouse con código único,
# lo que garantiza stock 100% independiente por sucursal.

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class CookastLocal(models.Model):
    _name = 'cookast.local'
    _description = 'Local / Sucursal de Franquicia Cookast'
    _rec_name = 'name'
    _order = 'sequence, name'

    # ── Identificación ────────────────────────────────────────────────────────
    name = fields.Char(
        string='Nombre del local',
        required=True,
        help='Ej: HUNDRED El Palmar, HUNDRED Avenida…',
    )
    short_code = fields.Char(
        string='Código corto',
        size=5,
        required=True,
        help='Código de 3-5 letras que se usará para el almacén (ej: HEP, HAV). '
             'Solo letras mayúsculas, sin espacios. No editable una vez guardado.',
    )
    active = fields.Boolean(string='Activo', default=True)
    sequence = fields.Integer(string='Secuencia', default=10)
    color = fields.Integer(string='Color', default=0)
    phone = fields.Char(string='Teléfono')
    email = fields.Char(string='Email')
    notes = fields.Text(string='Notas internas')

    # ── Dirección / Partner ───────────────────────────────────────────────────
    partner_id = fields.Many2one(
        'res.partner',
        string='Dirección postal',
        help='Contacto asociado al local para facturación y envíos.',
    )
    street = fields.Char(related='partner_id.street', readonly=True, string='Calle')
    city = fields.Char(related='partner_id.city', readonly=True, string='Ciudad')

    # ── Almacén y Stock ───────────────────────────────────────────────────────
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén',
        readonly=True,
        help='Almacén de Odoo asociado a este local. '
             'Se crea automáticamente al guardar el local por primera vez.',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Ubicación de stock',
        readonly=True,
        help='Ubicación principal de inventario de este local. '
             'Deriva del almacén creado automáticamente.',
    )

    # ── Personal ──────────────────────────────────────────────────────────────
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager del local',
        domain=[('cookast_level', '=', 'responsible')],
    )
    employee_ids = fields.Many2many(
        'hr.employee',
        'cookast_local_employee_rel',
        'local_id',
        'employee_id',
        string='Empleados asignados',
        help='Empleados que trabajan habitualmente en este local. '
             'Un empleado puede estar en varios locales (franquicia).',
    )

    # ── TPVs (Terminales Punto de Venta) ──────────────────────────────────────
    pos_config_ids = fields.One2many(
        'pos.config',
        'cookast_local_id',
        string='Terminales TPV',
    )

    # ── Estadísticas (computed) ───────────────────────────────────────────────
    forecast_count = fields.Integer(
        string='Previsiones',
        compute='_compute_stats',
    )
    employee_count = fields.Integer(
        string='Empleados',
        compute='_compute_stats',
    )
    pos_count = fields.Integer(
        string='TPVs',
        compute='_compute_stats',
    )
    last_forecast_date = fields.Date(
        string='Última previsión',
        compute='_compute_stats',
    )

    @api.depends('employee_ids', 'pos_config_ids')
    def _compute_stats(self):
        for local in self:
            forecasts = self.env['cookast.forecast'].search([
                ('local_id', '=', local.id),
            ])
            local.forecast_count = len(forecasts)
            local.employee_count = len(local.employee_ids)
            local.pos_count = len(local.pos_config_ids)
            dates = forecasts.mapped('date')
            local.last_forecast_date = max(dates) if dates else False

    # ── Constraints ───────────────────────────────────────────────────────────
    _sql_constraints = [
        ('unique_short_code', 'UNIQUE(short_code)',
         'Ya existe un local con este código corto. Usa uno diferente.'),
        ('unique_name', 'UNIQUE(name)',
         'Ya existe un local con este nombre.'),
    ]

    @api.constrains('short_code')
    def _check_short_code(self):
        for local in self:
            if not local.short_code:
                continue
            if not local.short_code.isalpha():
                raise ValidationError(_(
                    'El código corto "%s" solo puede contener letras (sin espacios ni números).'
                ) % local.short_code)

    # ── CRUD: auto-crear warehouse al crear el local ─────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('warehouse_id'):
                code = (vals.get('short_code') or vals.get('name', '')[:5]).upper()
                # Verificar que el código no esté ya en uso en warehouses
                existing = self.env['stock.warehouse'].search([('code', '=', code)], limit=1)
                if existing:
                    # Si ya existe, añadir sufijo numérico
                    suffix = 1
                    while existing:
                        new_code = f"{code[:4]}{suffix}"
                        existing = self.env['stock.warehouse'].search(
                            [('code', '=', new_code)], limit=1
                        )
                        suffix += 1
                    code = new_code

                _logger.info("Cookast: creando warehouse '%s' (código: %s) para el local '%s'",
                             vals.get('name'), code, vals.get('name'))
                warehouse = self.env['stock.warehouse'].create({
                    'name': vals.get('name'),
                    'code': code,
                    'company_id': self.env.company.id,
                })
                vals['warehouse_id'] = warehouse.id
                vals['location_id'] = warehouse.lot_stock_id.id
                # El short_code puede diferir si hubo conflicto de código
                if code != (vals.get('short_code') or '').upper():
                    vals['short_code'] = code

        return super().create(vals_list)

    # ── Acciones rápidas (smart buttons) ─────────────────────────────────────
    def action_view_forecasts(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Previsiones — %s') % self.name,
            'res_model': 'cookast.forecast',
            'view_mode': 'graph,pivot,list,form',
            'domain': [('local_id', '=', self.id)],
            'context': {'default_local_id': self.id},
        }

    def action_view_employees(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Empleados — %s') % self.name,
            'res_model': 'hr.employee',
            'view_mode': 'kanban,list,form',
            'domain': [('cookast_local_ids', 'in', self.id)],
            'context': {'default_cookast_local_ids': [(4, self.id)]},
        }

    def action_view_pos(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('TPVs — %s') % self.name,
            'res_model': 'pos.config',
            'view_mode': 'list,form',
            'domain': [('cookast_local_id', '=', self.id)],
            'context': {'default_cookast_local_id': self.id},
        }

    def action_view_stock(self):
        """Abre el inventario del almacén de este local."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Inventario — %s') % self.name,
            'res_model': 'stock.quant',
            'view_mode': 'list',
            'domain': [('location_id', 'child_of', self.location_id.id)],
            'context': {
                'default_location_id': self.location_id.id,
                'search_default_internal_loc': 1,
                'inventory_mode': True,
                'no_at_date': True,
            },
        }
