select m.numero_asiento_aicia as num,
       a.code_store->>'1' as acc,
       round(l.debit*100)::bigint as debit,
       round(l.credit*100)::bigint as credit,
       coalesce((select string_agg(c.code, '|') from aicia_partner_code c
                  where c.partner_id = l.partner_id and c.partner_type = 'customer'), '') as cli,
       coalesce((select string_agg(c.code, '|') from aicia_partner_code c
                  where c.partner_id = l.partner_id and c.partner_type = 'supplier'), '') as prov,
       coalesce((select string_agg(c.code, '|') from aicia_partner_code c
                  where c.partner_id = l.partner_id and c.partner_type = 'employee'), '') as emp
  from account_move_line l
  join account_move m on m.id = l.move_id
  join account_account a on a.id = l.account_id
 where m.numero_asiento_aicia is not null
