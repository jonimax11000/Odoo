# -*- coding: utf-8 -*-
"""
cookast_pos_stock.py
Bloqueo de ventas en TPV cuando faltan ingredientes en stock.

Flujo:
  1. El POS JS llama a `pos.order::check_ingredients_availability` vía RPC
     antes de procesar el pago.
  2. El método resuelve los BOMs tipo 'phantom' (Kit) de cada línea,
     suma todas las necesidades de ingredientes y compara con el stock
     disponible en el almacén del local asignado al TPV.
  3. Si algún ingrediente tiene stock < cantidad necesaria, devuelve la
     lista de problemas para que el JS pueda mostrar el error y bloquear.
  4. Para productos simples (sin BOM), se comprueba directamente el stock
     del producto.
"""

from odoo import models, api
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    @api.model
    def check_ingredients_availability(self, order_lines, config_id):
        """
        Verifica la disponibilidad de stock para todas las líneas del pedido.

        Parámetros (enviados desde el POS JS):
          - order_lines: list de dicts [{'product_id': int, 'qty': float}, ...]
          - config_id:   int — ID del pos.config activo (para obtener el almacén)

        Devuelve:
          {
            'ok': True/False,
            'errors': [
              {
                'product': 'Hamburguesa',
                'ingredient': 'Carne de Ternera',
                'needed': 2.0,
                'available': 0.5,
                'uom': 'kg',
              }, ...
            ]
          }
        """
        errors = []

        # ── Obtener el almacén del local vinculado al TPV ─────────────────────
        config = self.env['pos.config'].browse(config_id)
        warehouse = None
        location = None

        # Primero intentar por local Cookast
        if config.cookast_local_id and config.cookast_local_id.warehouse_id:
            warehouse = config.cookast_local_id.warehouse_id
        # Fallback: almacén del picking type del TPV
        elif config.picking_type_id and config.picking_type_id.warehouse_id:
            warehouse = config.picking_type_id.warehouse_id

        if warehouse:
            # Usar la ubicación interna raíz del almacén para el cálculo de stock
            location = warehouse.lot_stock_id  # ubicación de existencias principal

        # ── Acumular necesidades de ingredientes para todo el pedido ──────────
        # {product_id: {'qty_needed': float, 'parent_product_name': str, uom_id: int}}
        ingredient_needs = {}

        for line in order_lines:
            product_id = line.get('product_id')
            qty = line.get('qty', 0.0)
            if not product_id or qty <= 0:
                continue

            product = self.env['product.product'].browse(product_id)
            if not product.exists():
                continue

            # Buscar BOM tipo Kit (phantom) para este producto
            bom = self._find_kit_bom(product)

            if bom:
                # Producto compuesto: verificar cada ingrediente del BOM
                for bom_line in bom.bom_line_ids:
                    ingredient = bom_line.product_id
                    if not ingredient:
                        continue
                    # Escalar cantidad según qty pedida vs qty_bom del BOM
                    factor = qty / (bom.product_qty or 1.0)
                    qty_needed = bom_line.product_qty * factor

                    key = ingredient.id
                    if key not in ingredient_needs:
                        ingredient_needs[key] = {
                            'qty_needed': 0.0,
                            'parent_names': set(),
                            'product': ingredient,
                            'uom': ingredient.uom_id.name or '',
                        }
                    ingredient_needs[key]['qty_needed'] += qty_needed
                    ingredient_needs[key]['parent_names'].add(product.display_name)
            else:
                # Producto simple: verificar stock directo
                key = product.id
                if key not in ingredient_needs:
                    ingredient_needs[key] = {
                        'qty_needed': 0.0,
                        'parent_names': set(),
                        'product': product,
                        'uom': product.uom_id.name or '',
                        'is_direct': True,
                    }
                ingredient_needs[key]['qty_needed'] += qty
                ingredient_needs[key]['parent_names'].add(product.display_name)

        # ── Verificar stock de cada ingrediente ───────────────────────────────
        for product_id, need in ingredient_needs.items():
            ingredient = need['product']
            qty_needed = need['qty_needed']

            # Stock disponible: preferir por ubicación del almacén
            if location:
                qty_available = self._get_stock_in_location(ingredient, location)
            else:
                qty_available = ingredient.qty_available  # stock global

            if qty_available < qty_needed:
                is_direct = need.get('is_direct', False)
                parent_names = ', '.join(sorted(need['parent_names']))

                errors.append({
                    'product': parent_names,
                    'ingredient': ingredient.display_name if not is_direct else ingredient.display_name,
                    'needed': round(qty_needed, 3),
                    'available': round(max(qty_available, 0.0), 3),
                    'uom': need['uom'],
                    'is_ingredient': not is_direct,
                })

        return {
            'ok': len(errors) == 0,
            'errors': errors,
        }

    def _find_kit_bom(self, product):
        """
        Busca la BOM de tipo 'phantom' (Kit) activa para el producto.
        Devuelve el primer BOM encontrado o None.
        """
        BomModel = self.env['mrp.bom']
        # Buscar por producto variante
        bom = BomModel.search([
            ('product_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('active', '=', True),
        ], limit=1)

        if not bom:
            # Buscar por plantilla de producto
            bom = BomModel.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('product_id', '=', False),
                ('type', '=', 'phantom'),
                ('active', '=', True),
            ], limit=1)

        return bom or None

    def _get_stock_in_location(self, product, location):
        """
        Devuelve el stock disponible de un producto en una ubicación y
        todas sus sub-ubicaciones internas (sin incluir ubicaciones virtuales).
        """
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
            ('location_id.usage', '=', 'internal'),
        ])
        return sum(quants.mapped('quantity')) - sum(quants.mapped('reserved_quantity'))
