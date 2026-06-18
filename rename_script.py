import os
import re

directory = '/home/xtendoo/Documentos/odoo/19/odoo/custom/src/custom-aicia/aicia_account_pgc_recode'
for root, _, files in os.walk(directory):
    for file in files:
        filepath = os.path.join(root, file)
        with open(filepath, 'r') as f:
            content = f.read()
        
        # We want to replace account_pgc_recode with aicia_account_pgc_recode
        # But avoid double aicia_
        new_content = content.replace('aicia_account_pgc_recode', 'account_pgc_recode')
        new_content = new_content.replace('account_pgc_recode', 'aicia_account_pgc_recode')

        # Also account.pgc.recode
        new_content = new_content.replace('aicia.account.pgc.recode', 'account.pgc.recode')
        new_content = new_content.replace('account.pgc.recode', 'aicia.account.pgc.recode')

        if new_content != content:
            with open(filepath, 'w') as f:
                f.write(new_content)
            print(f"Updated {filepath}")
