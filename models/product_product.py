# models/product_product.py
from odoo import models, fields


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    category_type = fields.Selection([
        ('raw_material', 'Materia Prima'),
        ('prepared_food', 'Plato Preparado'),
        ('drink', 'Bebida'),
        ('other', 'Otro')
    ], string="Tipo de producto restaurante")


class ProductProduct(models.Model):
    _inherit = 'product.product'

    is_raw_material = fields.Boolean(string="Es materia prima")
    is_prepared_food = fields.Boolean(string="Es plato preparado")