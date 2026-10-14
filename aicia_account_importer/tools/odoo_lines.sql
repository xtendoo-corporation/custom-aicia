-- Líneas importadas por el importador AICIA, para el informe de conciliación.
-- Uso:  psql -U odoo -d <base> -f odoo_lines.sql   (genera odoo_lines.csv en el servidor de BD;
--       con docker: docker compose exec -T db psql -U odoo -d <base> -c "\copy (...) to stdout csv header" > odoo_lines.csv)
\copy (
  select m.numero_asiento_aicia as num,
         a.code_store->>'1' as acc,
         round(l.debit*100)::bigint as debit,
         round(l.credit*100)::bigint as credit,
         coalesce(substring(p.codigo_cliente from 2), '') as cli,
         coalesce(substring(p.codigo_proveedor from 2), '') as prov,
         coalesce((select string_agg(c.code, '|') from aicia_partner_code c
                    where c.partner_id = l.partner_id and c.partner_type = 'employee'), '') as emp
    from account_move_line l
    join account_move m on m.id = l.move_id
    join account_account a on a.id = l.account_id
    left join res_partner p on p.id = l.partner_id
   where m.numero_asiento_aicia is not null
) to 'odoo_lines.csv' csv header
