# Inicialización del módulo
# Manifest del módulo para previsualización de adjuntos
{
    'name': 'Previsualización de Adjuntos',
    'version': '17.0.1.0.0',
    'category': 'Tools',
    'summary': 'Añade botón para previsualizar adjuntos en su formulario',
    'author': 'Dani Domínguez - Xtendoo',
    'website': 'https://xtendoo.es',
    'depends': ['base', 'web'],
    'data': [
        'views/ir_attachment_preview_button.xml',
        'views/ir_attachment_preview_pdf.xml',  # Añadida vista para previsualización PDF
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
