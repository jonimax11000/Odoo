# -*- coding: utf-8 -*-
from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class CookastSyncLog(models.Model):
    _name = 'cookast.sync.log'
    _description = 'Log de sincronizaciones Cookast'
    _order = 'sync_date desc'
    _rec_name = 'sync_date'

    sync_date = fields.Datetime(
        string='Fecha de sincronización',
        default=fields.Datetime.now,
        readonly=True,
    )
    model_synced = fields.Char(string='Modelo sincronizado', readonly=True)
    records_processed = fields.Integer(string='Registros procesados', readonly=True)
    status = fields.Selection(
        [('success', 'Éxito'), ('error', 'Error')],
        string='Estado',
        readonly=True,
    )
    error_message = fields.Text(string='Mensaje de error', readonly=True)

    @api.model
    def _log(self, model_name, records_processed, status, error_message=None):
        """Helper para crear entradas de log desde otros métodos."""
        self.create({
            'model_synced': model_name,
            'records_processed': records_processed,
            'status': status,
            'error_message': error_message,
        })
        if status == 'error':
            _logger.error("Cookast sync error on %s: %s", model_name, error_message)
        else:
            _logger.info("Cookast sync OK on %s: %d records", model_name, records_processed)
