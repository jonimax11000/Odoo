import re
import os
import glob

def clean_views():
    directory = r'c:\Users\Usuario\Desktop\Óptica\Odoo\odoo19\custom-addons\cookast\views'
    for filepath in glob.glob(os.path.join(directory, '*.xml')):
        with open(filepath, 'r', encoding='utf-8') as f:
            data = f.read()
            
        # Replace <tree with <list
        data = re.sub(r'<tree([^>]*)>', r'<list\1>', data)
        data = re.sub(r'</tree>', r'</list>', data)
        
        # Remove string="xxx" from roots
        for tag in ['list', 'form', 'search', 'pivot', 'graph']:
            data = re.sub(r'<(%s)\s+string="[^"]*"' % tag, r'<\1', data)
            data = re.sub(r'<(%s)\s+expand="[^"]*"' % tag, r'<\1', data)
            
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(data)

if __name__ == '__main__':
    clean_views()
