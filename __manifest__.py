{
    'name': 'Cookast Weather',
    'version': '19.0.1.0.0',
    'category': 'Operations/Foodservice',
    'summary': 'Previsión meteorológica semanal por local para Cookast',
    'author': 'Apunts Informática',
    'website': 'https://apuntsinformatica.apuntserp.es/',
    'license': 'LGPL-3',
    'depends': ['cookast'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'views/cookast_weather_views.xml',
        'reports/weather_forecast_report.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}