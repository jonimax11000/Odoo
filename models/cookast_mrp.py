# models/cookast_mrp.py
# Extensión del módulo MRP nativo de Odoo para añadir:
#   - Campos extra en mrp.bom (merma, tiempo preparación)
#   - Campos de stock en mrp.bom.line (stock disponible, estado)
#   - Vista SQL de análisis de necesidades de materia prima

from odoo import models, fields, api, tools, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# EXTENSIÓN DE mrp.bom (Lista de Materiales nativa de Odoo)
# ═════════════════════════════════════════════════════════════════════════════

class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    # ── Campos extra Cookast ─────────────────────────────────────────────────
    waste_percentage = fields.Float(
        string='% Merma',
        default=0.0,
        help='Porcentaje de desperdicio/merma estimado para esta lista de materiales',
    )
    prep_time_minutes = fields.Integer(
        string='Tiempo Preparación (min)',
        help='Tiempo estimado de preparación en minutos',
    )
    cookast_notes = fields.Html(
        string='Notas Cookast',
        help='Notas internas sobre esta composición',
    )

    # ── Coste total calculado ────────────────────────────────────────────────
    cookast_total_cost = fields.Float(
        string='Coste Total Componentes',
        compute='_compute_cookast_cost',
        store=True,
        digits='Product Price',
    )
    cookast_unit_cost = fields.Float(
        string='Coste Unitario',
        compute='_compute_cookast_cost',
        store=True,
        digits='Product Price',
    )

    @api.depends('bom_line_ids.product_id', 'bom_line_ids.product_qty', 'product_qty')
    def _compute_cookast_cost(self):
        for bom in self:
            total = sum(
                line.product_id.standard_price * line.product_qty
                for line in bom.bom_line_ids
                if line.product_id
            )
            bom.cookast_total_cost = total
            bom.cookast_unit_cost = total / bom.product_qty if bom.product_qty else 0.0

    # ── Contador de componentes ──────────────────────────────────────────────
    cookast_component_count = fields.Integer(
        string='Nº Componentes',
        compute='_compute_cookast_component_count',
    )

    @api.depends('bom_line_ids')
    def _compute_cookast_component_count(self):
        for bom in self:
            bom.cookast_component_count = len(bom.bom_line_ids)


# ═════════════════════════════════════════════════════════════════════════════
# EXTENSIÓN DE mrp.bom.line (Líneas / Componentes)
# ═════════════════════════════════════════════════════════════════════════════

class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    # ── Info de Stock (en vivo) ──────────────────────────────────────────────
    cookast_qty_available = fields.Float(
        string='Stock Disponible',
        related='product_id.qty_available',
        readonly=True,
    )
    cookast_virtual_available = fields.Float(
        string='Stock Previsto',
        related='product_id.virtual_available',
        readonly=True,
    )
    cookast_line_cost = fields.Float(
        string='Coste Línea',
        compute='_compute_cookast_line_cost',
        digits='Product Price',
    )
    cookast_stock_status = fields.Selection(
        [('ok', 'Suficiente'), ('low', 'Bajo'), ('out', 'Sin Stock')],
        string='Estado Stock',
        compute='_compute_cookast_stock_status',
    )

    @api.depends('product_id.standard_price', 'product_qty')
    def _compute_cookast_line_cost(self):
        for line in self:
            line.cookast_line_cost = (
                line.product_id.standard_price * line.product_qty
                if line.product_id else 0.0
            )

    @api.depends('cookast_qty_available', 'product_qty')
    def _compute_cookast_stock_status(self):
        for line in self:
            if line.cookast_qty_available <= 0:
                line.cookast_stock_status = 'out'
            elif line.cookast_qty_available < line.product_qty * 5:
                line.cookast_stock_status = 'low'
            else:
                line.cookast_stock_status = 'ok'


# ═════════════════════════════════════════════════════════════════════════════
# ANÁLISIS DE NECESIDADES DE MATERIA PRIMA (Vista SQL)
# ═════════════════════════════════════════════════════════════════════════════

class CookastMaterialNeed(models.Model):
    _name = 'cookast.material.need'
    _description = 'Análisis de Necesidades de Materia Prima'
    _order = 'stock_status desc, product_id'
    _auto = False  # Vista SQL — no se crea tabla real

    local_id = fields.Many2one('cookast.local', string='Local', readonly=True)
    product_id = fields.Many2one('product.product', string='Materia Prima', readonly=True)
    product_name = fields.Char(string='Nombre', readonly=True)
    uom_id = fields.Many2one('uom.uom', string='UdM', readonly=True)
    qty_available = fields.Float(string='Stock Actual', readonly=True)
    virtual_available = fields.Float(string='Stock Previsto', readonly=True)
    total_needed = fields.Float(string='Necesidad Total (LdM)', readonly=True)
    qty_to_purchase = fields.Float(string='Cantidad a Comprar', readonly=True)
    unit_cost = fields.Float(string='Coste Unitario', readonly=True)
    purchase_cost = fields.Float(string='Coste Compra Estimado', readonly=True)
    bom_count = fields.Integer(string='Nº LdM que lo usan', readonly=True)
    stock_status = fields.Selection(
        [('ok', 'Suficiente'), ('low', 'Bajo'), ('out', 'Sin Stock')],
        string='Estado',
        readonly=True,
    )

    def init(self):
        """
        Vista SQL que cruza todas las líneas de LdM activas con el stock
        actual para calcular necesidades de compra.
        Usa las tablas nativas de Odoo: mrp_bom y mrp_bom_line.
        """
        tools.drop_view_if_exists(self.env.cr, self._table)

        # Detectar si standard_price es JSONB (Odoo 19 multi-company)
        # o numérico normal
        self.env.cr.execute("""
            SELECT data_type
            FROM information_schema.columns
            WHERE table_name = 'product_product'
              AND column_name = 'standard_price'
        """)
        result = self.env.cr.fetchone()
        if result and result[0] == 'jsonb':
            price_expr = "(pp.standard_price ->> '1')::numeric"
        else:
            price_expr = "pp.standard_price"

        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    CAST((pp.id::varchar || cl.id::varchar) AS integer) AS id,
                    cl.id AS local_id,
                    pp.id AS product_id,
                    COALESCE(
                        pt.name ->> 'es_ES',
                        pt.name ->> 'en_US',
                        pt.name::text
                    ) AS product_name,
                    pt.uom_id,
                    COALESCE(sq.qty_available, 0) AS qty_available,
                    COALESCE(sq.qty_available, 0) AS virtual_available,
                    COALESCE(SUM(bl.product_qty), 0) AS total_needed,
                    GREATEST(
                        COALESCE(SUM(bl.product_qty), 0) - COALESCE(sq.qty_available, 0),
                        0
                    ) AS qty_to_purchase,
                    COALESCE({price_expr}, 0.0) AS unit_cost,
                    GREATEST(
                        COALESCE(SUM(bl.product_qty), 0) - COALESCE(sq.qty_available, 0),
                        0
                    ) * COALESCE({price_expr}, 0.0) AS purchase_cost,
                    COUNT(DISTINCT b.id) AS bom_count,
                    CASE
                        WHEN COALESCE(sq.qty_available, 0) <= 0 THEN 'out'
                        WHEN COALESCE(sq.qty_available, 0) < COALESCE(SUM(bl.product_qty), 0) THEN 'low'
                        ELSE 'ok'
                    END AS stock_status
                FROM product_product pp
                    JOIN product_template pt ON pt.id = pp.product_tmpl_id
                    CROSS JOIN cookast_local cl
                    LEFT JOIN mrp_bom_line bl ON bl.product_id = pp.id
                    LEFT JOIN mrp_bom b ON b.id = bl.bom_id AND b.active = TRUE
                    LEFT JOIN (
                        SELECT sq_inner.product_id, sl.warehouse_id, SUM(sq_inner.quantity) AS qty_available
                        FROM stock_quant sq_inner
                        JOIN stock_location sl ON sq_inner.location_id = sl.id
                        WHERE sl.usage = 'internal'
                        GROUP BY sq_inner.product_id, sl.warehouse_id
                    ) sq ON sq.product_id = pp.id AND sq.warehouse_id = cl.warehouse_id
                WHERE pt.is_storable = TRUE
                GROUP BY
                    cl.id, pp.id, pt.name, pt.uom_id,
                    sq.qty_available, {price_expr}
            );
        """)

    def action_create_purchase_order(self):
        """Crea un pedido de compra con las materias primas seleccionadas."""
        lines = self
        if not lines:
            raise UserError(_('Debe seleccionar al menos un producto para reabastecer.'))

        # Agrupar por (proveedor, local)
        supplier_local_lines = {}
        no_supplier = []
        for line in lines:
            sellers = line.product_id.seller_ids
            if sellers:
                supplier = sellers[0].partner_id
                key = (supplier.id, line.local_id.id)
                supplier_local_lines.setdefault(key, {
                    'partner': supplier,
                    'local': line.local_id,
                    'lines': [],
                })
                supplier_local_lines[key]['lines'].append(line)
            else:
                no_supplier.append(line.product_id.display_name)

        if not supplier_local_lines:
            raise UserError(_(
                'Ninguna de las materias primas seleccionadas tiene un proveedor configurado.\n'
                'Configure proveedores en las fichas de producto.'
            ))

        created_pos = self.env['purchase.order']
        for (supplier_id, local_id), data in supplier_local_lines.items():
            po_lines = [(0, 0, {
                'product_id': line.product_id.id,
                'name': line.product_id.display_name,
                'product_qty': line.qty_to_purchase or 1.0,
                'product_uom_id': line.uom_id.id,
                'price_unit': line.unit_cost,
            }) for line in data['lines']]

            # Encontrar el tipo de operación "Receipts" (incoming) del almacén del local
            picking_type = False
            if data['local']:
                picking_type = self.env['stock.picking.type'].search([
                    ('warehouse_id', '=', data['local'].warehouse_id.id),
                    ('code', '=', 'incoming')
                ], limit=1)

            po_vals = {
                'partner_id': data['partner'].id,
                'order_line': po_lines,
            }
            if picking_type:
                po_vals['picking_type_id'] = picking_type.id

            po = self.env['purchase.order'].create(po_vals)
            created_pos |= po

        # Si solo se creó 1 PO, abrir directamente
        if len(created_pos) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Pedido de Compra Generado'),
                'res_model': 'purchase.order',
                'res_id': created_pos.id,
                'view_mode': 'form',
                'target': 'current',
            }

        # Si se crearon varios, mostrar lista
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pedidos de Compra Generados'),
            'res_model': 'purchase.order',
            'domain': [('id', 'in', created_pos.ids)],
            'view_mode': 'list,form',
            'target': 'current',
        }