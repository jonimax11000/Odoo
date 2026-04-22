# -*- coding: utf-8 -*-
{
    'name': 'Cookast Connector',
    'version': '19.0.1.0.0',
    'category': 'Operations/Foodservice',
    'summary': 'Integración con Cookast: Previsiones, Compras y Personal',
    'description': """
        Fase 1: Sincronización de datos Odoo → tablas resumen Cookast.
        - Previsiones de venta por local y turno (POS)
        - Presupuesto vs gasto real de compras por categoría
        - Extensión de empleados con datos de nivel Cookast
        - Planificación de turnos y coste
        - Log de sincronizaciones automáticas
    """,
    'author': 'Apunts Informática',
    'website': 'https://apuntsinformatica.apuntserp.es/',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'point_of_sale',
        'purchase',
        'sale_management',
        'hr',
        'stock',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/cookast_menu.xml',
        'views/dashboard_views.xml',
        'views/employee_views.xml',
        'views/shift_plan_views.xml',
        'views/purchase_views.xml',
        'views/ai_placeholder.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
