import os
import shutil

src_dir = '/home/xtendoo/Documentos/odoo/19/odoo/custom/src/custom-aicia/account_pgc_recode'
dst_dir = '/home/xtendoo/Documentos/odoo/19/odoo/custom/src/custom-aicia/aicia_account_pgc_recode'

# 1. Update contents in the new directory
for root, _, files in os.walk(dst_dir):
    for file in files:
        filepath = os.path.join(root, file)
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            new_content = content.replace('aicia_account_pgc_recode', 'account_pgc_recode')
            new_content = new_content.replace('account_pgc_recode', 'aicia_account_pgc_recode')

            new_content = new_content.replace('aicia.account.pgc.recode', 'account.pgc.recode')
            new_content = new_content.replace('account.pgc.recode', 'aicia.account.pgc.recode')

            if new_content != content:
                with open(filepath, 'w') as f:
                    f.write(new_content)
                print(f"Updated references in {filepath}")
        except Exception as e:
            print(f"Error processing {filepath}: {e}")

# 2. Delete old directory
if os.path.exists(src_dir):
    try:
        shutil.rmtree(src_dir)
        print(f"Deleted old directory: {src_dir}")
    except Exception as e:
        print(f"Error deleting {src_dir}: {e}")
