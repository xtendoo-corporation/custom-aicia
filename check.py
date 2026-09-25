import os

dst_dir = '/home/xtendoo/Documentos/odoo/19/odoo/custom/src/custom-aicia/aicia_account_pgc_recode'
found = False

for root, _, files in os.walk(dst_dir):
    for file in files:
        filepath = os.path.join(root, file)
        try:
            with open(filepath, 'r') as f:
                content = f.read()
            
            # Count occurrences of 'account_pgc_recode'
            total_matches = content.count('account_pgc_recode')
            aicia_matches = content.count('aicia_account_pgc_recode')
            
            if total_matches > aicia_matches:
                print(f"Found missing replacements in {filepath}: {total_matches} vs {aicia_matches}")
                found = True
        except Exception as e:
            pass

if not found:
    print("All good, no missing replacements found!")
