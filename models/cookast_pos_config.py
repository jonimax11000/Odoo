# -*- coding: utf-8 -*-
# models/cookast_pos_config.py
# Vincula pos.config (Terminal Punto de Venta) con cookast.local.
# Un local puede tener varios TPVs (ej: barra + terraza).
# También extiende pos.order para heredar el local desde la config del TPV.

from odoo import models, fields, api


class PosConfig(models.Model):
    """Extensión del Terminal Punto de Venta con datos de local Cookast."""
    _inherit = 'pos.config'

    cookast_local_id = fields.Many2one(
        'cookast.local',
        string='Local Cookast',
        index=True,
        help='Local al que pertenece este Terminal Punto de Venta. '
             'Si está configurado, los pedidos POS de este terminal '
             'se vincularán automáticamente al forecast del local.',
    )

    # Campo relacionado para mostrar el almacén del local directamente
    cookast_warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Almacén del local',
        related='cookast_local_id.warehouse_id',
        readonly=True,
        help='Almacén de stock del local. Considera configurar el almacén '
             'del TPV para que coincida con el del local.',
    )

    @api.onchange('cookast_local_id')
    def _onchange_cookast_local_id(self):
        if self.cookast_local_id and self.cookast_local_id.warehouse_id:
            # Buscar el tipo de operación "POS Orders" (o "Delivery Orders") del almacén del local
            picking_type = self.env['stock.picking.type'].search([
                ('warehouse_id', '=', self.cookast_local_id.warehouse_id.id),
                ('code', '=', 'outgoing')
            ], limit=1)
            if picking_type:
                self.picking_type_id = picking_type.id


class PosOrder(models.Model):
    """Extiende pos.order para propagar el local desde la config del TPV."""
    _inherit = 'pos.order'

    cookast_local_id = fields.Many2one(
        'cookast.local',
        string='Local Cookast',
        compute='_compute_cookast_local_id',
        store=True,
        index=True,
    )

    @api.depends('config_id.cookast_local_id')
    def _compute_cookast_local_id(self):
        for order in self:
            order.cookast_local_id = order.config_id.cookast_local_id
