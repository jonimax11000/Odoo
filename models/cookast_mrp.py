# models/cookast_mrp.py
from odoo import models, fields, api
from odoo.exceptions import UserError

class CookastBom(models.Model):
    _name = 'cookast.bom'
    _description = 'Receta Cookast'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Nombre Receta', required=True)
    product_id = fields.Many2one(
        'product.product', 
        string='Producto Final',
        domain=[('cookast_product_type', '=', 'prepared_food')],
        required=True
    )
    bom_line_ids = fields.One2many(
        'cookast.bom.line',
        'bom_id',
        string='Ingredientes'
    )
    forecast_ids = fields.One2many(
        'cookast.forecast.line',
        'bom_id',
        string='Previsiones Relacionadas'
    )
    
    # Métricas
    total_cost = fields.Float(
        string='Coste Total', 
        compute='_compute_total_cost', 
        store=True
    )
    waste_percentage = fields.Float(
        string='% Merma', 
        default=5.0,
        help='Porcentaje de desperdicio estimado'
    )
    prep_time_minutes = fields.Integer(string='Tiempo Prep (min)')
    
    @api.depends('bom_line_ids.total_cost')
    def _compute_total_cost(self):
        for rec in self:
            rec.total_cost = sum(line.total_cost for line in rec.bom_line_ids)
    
    def action_create_mrp_bom(self):
        """Crea un BoM estándar de Odoo desde la receta Cookast"""
        self.ensure_one()
        mrp_bom = self.env['mrp.bom'].create({
            'product_tmpl_id': self.product_id.product_tmpl_id.id,
            'product_id': self.product_id.id,
            'type': 'normal',
            'bom_line_ids': [(0, 0, {
                'product_id': line.ingredient_id.id,
                'product_qty': line.quantity,
                'product_uom_id': line.uom_id.id,
            }) for line in self.bom_line_ids]
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.bom',
            'res_id': mrp_bom.id,
            'view_mode': 'form',
            'target': 'current',
        }


class CookastBomLine(models.Model):
    _name = 'cookast.bom.line'
    _description = 'Ingrediente de Receta'
    
    bom_id = fields.Many2one('cookast.bom', string='Receta', required=True)
    ingredient_id = fields.Many2one(
        'product.product',
        string='Ingrediente',
        domain=[('cookast_product_type', '=', 'raw_material')],
        required=True
    )
    quantity = fields.Float(string='Cantidad', required=True)
    uom_id = fields.Many2one(
        'uom.uom',
        string='UdM',
        related='ingredient_id.uom_id',
        readonly=True
    )
    unit_cost = fields.Float(
        string='Coste Unitario',
        related='ingredient_id.standard_price',
        readonly=True
    )
    total_cost = fields.Float(
        string='Coste Total',
        compute='_compute_total_cost',
        store=True
    )
    
    @api.depends('quantity', 'unit_cost')
    def _compute_total_cost(self):
        for line in self:
            line.total_cost = line.quantity * line.unit_cost