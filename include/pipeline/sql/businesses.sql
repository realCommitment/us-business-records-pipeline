-- One row per business seen in any source, with the records of the same
-- business merged in product decision 9's five steps, and no filter. Names no
-- state: registries and trade names arrive in the states contract's columns.
-- Inputs come from SET VARIABLE: registry and dba (lists of stage paths),
-- ppp, filings, sba, sam and fmcsa (stage paths), run_date and naics_titles (the
-- Census code list).

-- A date that can count as evidence: 1900-01-01 is the sources' placeholder,
-- never a founding date, and a date after run_date is a typo.
create or replace temp macro evidence_date(d) as
    if(d = date '1900-01-01' or d > getvariable('run_date')::DATE, null, d);

-- nullif: a PO box yields '', which would match every PO box in the ZIP
create or replace temp macro street_no(a) as
    nullif(regexp_extract(a, '^\s*(\d+)', 1), '');

-- The sources as registry rows (reg), trade-name rows (dba), plan sponsors
-- (spon) and PPP keys (ppp_key). source is the stage file's name.
create or replace table reg as
select * exclude (filename),
       regexp_extract(filename, '([^/]+)\.parquet$', 1) as source,
       street_no(address) as street_no
from read_parquet(getvariable('registry'), union_by_name=true, filename=true);

create or replace table dba as
select * exclude (filename),
       regexp_extract(filename, '([^/]+)\.parquet$', 1) as source
from read_parquet(getvariable('dba'), union_by_name=true, filename=true);

-- A sponsor is an EIN with a US address. Its name, phone and plan columns
-- come from its latest filing, and its address from its latest filing with
-- a US state; an EIN that only ever filed from abroad is not a US business.
-- ack_id starts with the submission timestamp, so it makes same-day ties
-- stable.
create or replace table spon as
select ein, sponsor_name, sponsor_dba_name, norm_name, us.address, us.city,
       us.state, us.zip5, street_no(us.address) as street_no, phone,
       business_code, plan_name, earliest_plan_eff_date, date_received,
       ever_defined_benefit, active_participants, pension_codes,
       signer_name, signer_source
from (
    select *,
           arg_max({'address': address, 'city': city, 'state': state,
                    'zip5': zip5}, (date_received, plan_year_begin, ack_id))
               filter (where state is not null) over (partition by ein) as us,
           min(plan_eff_date) over (partition by ein) as earliest_plan_eff_date,
           bool_or(is_defined_benefit) over (partition by ein)
               as ever_defined_benefit
    from read_parquet(getvariable('filings'))
)
where us is not null
qualify row_number() over (
    partition by ein
    order by date_received desc, plan_year_begin desc, ack_id desc) = 1;

create or replace table ppp_loan as
select * from read_parquet(getvariable('ppp'));

-- every pick has a tiebreaker, so unchanged input gives an unchanged file:
-- longest name, then latest loan, then loan number
create or replace table ppp_key as
select *, 'ppp' as source, zip5 || '|' || norm_name as rec_id,
       street_no(address) as street_no
from (
    select norm_name, zip5,
           arg_max(borrower_name, (length(borrower_name), borrower_name))
               as business_name,
           min(dba_norm_name) as dba_norm_name,
           arg_max(address, (date_approved, loan_number)) as address,
           arg_max(city, (date_approved, loan_number)) as city,
           arg_max(state, (date_approved, loan_number)) as state,
           arg_max(business_type, (date_approved, loan_number)) as business_type,
           arg_max(business_age_description, (date_approved, loan_number))
               as business_age_description,
           bool_or(nonprofit) as nonprofit,
           bool_or(coalesce(loan_status = 'Charged Off', false)) as charged_off,
           max(loan_status_date) filter (where loan_status = 'Charged Off')
               as charge_off_date,
           max(jobs_reported) as jobs_reported,
           count(*) as ppp_loan_count,
           -- DECIMAL: a parallel DOUBLE sum differs in the last bits run to run
           sum(current_approval_amount::DECIMAL(18, 2)) as ppp_total_approved,
           min(date_approved) as ppp_first_loan_date,
           max(date_approved) as ppp_last_loan_date
    from ppp_loan
    group by norm_name, zip5
);

-- SBA loans have no id; loan_key numbers them in the order of the whole row
-- as text, so it breaks ties between loans of the same day the same way on
-- every run (identical rows are interchangeable).
create or replace table sba_loan as
select *, row_number() over (order by l::VARCHAR) as loan_key
from read_parquet(getvariable('sba')) l;

-- SBA borrowers: loans grouped by (norm_name, zip5). The place comes from the
-- latest loan, the reported age bucket from the earliest.
create or replace table sba_key as
select * exclude (place), place.address, place.city, place.state,
       'sba' as source, zip5 || '|' || norm_name as rec_id,
       street_no(place.address) as street_no
from (
    select norm_name, zip5,
           arg_max(borrower_name, (length(borrower_name), borrower_name))
               as business_name,
           min(dba_norm_name) as dba_norm_name,
           -- one struct, so the address, city and state are one loan's
           arg_max({'address': address, 'city': city, 'state': state},
                   (approval_date, loan_key)) as place,
           arg_max(naics, (approval_date, loan_key)) filter (where naics is not null)
               as naics,
           -- _null: the first loan's bucket even when it is blank
           arg_min_null(business_age, (approval_date, loan_key))
               as first_business_age,
           list(distinct program order by program) as programs,
           count(*) as loan_count,
           sum(gross_approval) as total_approved,
           min(approval_date) as first_loan_date,
           max(approval_date) as last_loan_date,
           bool_or(loan_status = 'CHGOFF') as charged_off,
           max(evidence_date(charge_off_date)) as charge_off_date
    from sba_loan
    group by norm_name, zip5
);

-- SAM entities in the US. rec_id is the UEI with its EFT indicator, unique;
-- several registrations of one UEI are one entity.
create or replace table sam_rec as
select *, 'sam' as source, uei || coalesce('-' || eft_indicator, '') as rec_id,
       street_no(address_1) as street_no
from read_parquet(getvariable('sam'))
where country = 'USA';

-- FMCSA carriers in the US with a state: a business needs one, and a carrier
-- abroad (or the 2 US ones without a state in October 2026, a Yukon address
-- and a test record) has none. rec_id is the USDOT number.
create or replace table fmcsa_rec as
select *, 'fmcsa' as source, dot_number::VARCHAR as rec_id,
       street_no(phy_street) as street_no
from read_parquet(getvariable('fmcsa'))
where phy_country = 'US' and phy_state is not null;

-- Tiers 1 to 3 of decision 9 between table l (rec, state, norm_name, zip5,
-- city, street_no) and table r (target, the same columns). A tier accepts a
-- record only when exactly one target fits; the best tier wins.
create or replace temp macro tiers(l, r) as table
select rec, target, tier, sim from (
    select * from (
        select l.rec, r.target, 1 as tier, 1.0 as sim
        from query_table(l) l join query_table(r) r
          on r.state = l.state and r.norm_name = l.norm_name and r.zip5 = l.zip5
        union all
        select l.rec, r.target, 2, 1.0
        from query_table(l) l join query_table(r) r
          on r.state = l.state and r.norm_name = l.norm_name and r.city = l.city
        union all
        -- blocked on ZIP and street number on purpose: no fuzzy matching
        -- across ZIPs
        select l.rec, r.target, 3, jaro_winkler_similarity(l.norm_name, r.norm_name)
        from query_table(l) l join query_table(r) r
          on r.state = l.state and r.zip5 = l.zip5 and r.street_no = l.street_no
        where jaro_winkler_similarity(l.norm_name, r.norm_name) >= 0.92
    )
    qualify count(distinct target) over (partition by rec, tier) = 1
)
qualify row_number() over (partition by rec order by tier, sim desc) = 1;

-- Step 1, anchors: every registry row is a business, and so is every
-- trade-name taxpayer with no registry row in its state.
create or replace table reg_b as
select *, coalesce('EIN-' || ein, state || '-' || registry_id) as business_id
from reg;

create or replace table dba_b as
select d.*, coalesce(r.business_id, 'EIN-' || o.ein,
                     d.state || '-' || d.registry_id) as business_id
from dba d
left join (select distinct state, registry_id, business_id from reg_b) r
  using (state, registry_id)
left join (select state, registry_id, min(ein) as ein from dba group by all) o
  using (state, registry_id);

-- Step 2, sponsors: by exact EIN in any state, else by tiers 1 to 3 against
-- registry rows of their state that carry no EIN, else a business of their
-- own.
create or replace table l_spon as
select ein as rec, state, norm_name, zip5, city, street_no from spon;
create or replace table r_reg_no_ein as
select business_id as target, state, norm_name, zip5, city, street_no
from reg_b where ein is null;

create or replace table spon_link as
select s.ein,
       coalesce(e.business_id, n.target, 'EIN-' || s.ein) as business_id,
       case when e.business_id is not null then 'ein'
            when n.target is not null then 'name' end as plan_link
from spon s
-- an EIN is national: a sponsor filing from another state is still that
-- registry entity, and both would carry the same EIN- business_id anyway
left join (
    select distinct ein, business_id from reg_b where ein is not null
    union
    select distinct ein, business_id from dba_b where ein is not null
) e on e.ein = s.ein
left join tiers('l_spon', 'r_reg_no_ein') n on n.rec = s.ein;


-- Step 3, records: tiers 1 to 4 against registry and trade-name businesses,
-- then tiers 5 to 7 against sponsors, which are computed for every record.
-- rk is unique across sources.
-- own_id is the business_id a record takes when it stands alone without a
-- key of its own; SAM and FMCSA records also try tiers 1 to 3 on their DBA
-- name.
create or replace table rec as
select source || '|' || rec_id as rk, source, rec_id, 'PPP-' || rec_id as own_id,
       state, norm_name, dba_norm_name, zip5, city, street_no,
       false as dba_tiers
from ppp_key
union all
select source || '|' || rec_id, source, rec_id, 'SBA-' || rec_id, state,
       norm_name, dba_norm_name, zip5, city, street_no, false
from sba_key
union all
select source || '|' || rec_id, source, rec_id, 'SAM-' || uei, state, norm_name,
       norm_dba_name, zip5, city, street_no, true
from sam_rec
union all
select source || '|' || rec_id, source, rec_id, 'DOT-' || rec_id, phy_state,
       norm_name, norm_dba_name, zip5, phy_city, street_no, true
from fmcsa_rec;

create or replace table l_rec as
select rk as rec, state, norm_name, zip5, city, street_no from rec;
create or replace table l_rec_dba as
select rk as rec, state, dba_norm_name as norm_name, zip5, city, street_no
from rec where dba_tiers and dba_norm_name is not null;
create or replace table r_reg as
select business_id as target, state, norm_name, zip5, city, street_no from reg_b;
create or replace table r_spon as
select ein as target, state, norm_name, zip5, city, street_no from spon;

-- tier 4 is two equi-joins rather than one OR join, so both stay hash joins
create or replace table t4 as
select rk, business_id from (
    select r.rk, d.business_id
    from rec r join dba_b d
      on d.state = r.state and d.zip5 = r.zip5 and d.norm_dba_name = r.norm_name
    union all
    select r.rk, d.business_id
    from rec r join dba_b d
      on d.state = r.state and d.zip5 = r.zip5 and d.norm_dba_name = r.dba_norm_name
)
qualify count(distinct business_id) over (partition by rk) = 1
    and row_number() over (partition by rk order by business_id) = 1;

create or replace table rec_reg as
select * from (
    select rec as rk, target as business_id, tier, sim from tiers('l_rec', 'r_reg')
    union all
    select rk, business_id, 4, 1.0 from t4
)
qualify row_number() over (partition by rk order by tier, sim desc) = 1;

-- a DBA name's tiers 1 to 3 count only when the legal name fits nothing in
-- tiers 1 to 7
create or replace table rec_reg_dba as
select rec as rk, target as business_id, tier, sim from tiers('l_rec_dba', 'r_reg');

create or replace table rec_spon as
select rec as rk, target as ein, tier + 4 as tier, sim
from tiers('l_rec', 'r_spon');

-- Step 5, one hop for plans: a sponsor left on its own joins the registry
-- business of the records that matched it in tiers 5 to 7, when all of them
-- are in that one business.
create or replace table hop as
select s.ein, min(g.business_id) as business_id
from rec_spon s
join spon_link l on l.ein = s.ein and l.plan_link is null
left join rec_reg g using (rk)
group by s.ein
having count(g.business_id) = count(*) and count(distinct g.business_id) = 1;

create or replace table spon_b as
select l.ein, coalesce(h.business_id, l.business_id) as business_id,
       if(h.business_id is not null, 'hop', l.plan_link) as plan_link
from spon_link l left join hop h using (ein);

-- Step 4, leftovers: records that joined nothing group by (norm_name, zip5),
-- one record per source; a source's records that share a key stay apart
-- under their own id.
-- key_count counts distinct own ids: several registrations of one SAM UEI
-- hold its key alone
create or replace table rec_m as
select r.*, coalesce(g.business_id, b.business_id, gd.business_id) as matched,
       count(distinct r.own_id) over (partition by r.source, r.norm_name, r.zip5)
           as key_count,
       coalesce(g.tier, if(b.business_id is not null, s.tier, null), gd.tier)
           as match_tier,
       coalesce(g.sim, if(b.business_id is not null, s.sim, null), gd.sim)
           as match_similarity
from rec r
left join rec_reg g using (rk)
left join rec_spon s using (rk)
left join spon_b b on b.ein = s.ein
left join rec_reg_dba gd using (rk);

-- A record that matched nothing joins the business that other sources'
-- records with its exact key matched, when they all matched the same one: a
-- PPP key and an SBA borrower of one (norm_name, zip5) are one business even
-- when only one of them fits a registry or sponsor.
create or replace table key_b as
select m.rk, min(o.matched) as business_id
from rec_m m
join rec_m o
  on o.norm_name = m.norm_name and o.zip5 = m.zip5 and o.source != m.source
where m.matched is null and o.matched is not null and m.key_count = 1
group by m.rk
having count(distinct o.matched) = 1;

create or replace table rec_b as
select m.rk, m.source, m.rec_id, m.state, m.norm_name, m.dba_norm_name, m.zip5,
       coalesce(m.matched, k.business_id,
                if(m.key_count = 1 and m.norm_name is not null and m.zip5 is not null,
                   'KEY-' || m.zip5 || '-' || m.norm_name, m.own_id)) as business_id,
       m.match_tier, m.match_similarity
from rec_m m
left join key_b k using (rk);

-- Every staged record and the business it landed in; qc checks conservation
-- against it.
create or replace table members as
select business_id, source, registry_id as rec_id, null::INTEGER as match_tier,
       null::VARCHAR as plan_link
from reg_b
union all
select distinct business_id, source, registry_id, null, null from dba_b
union all
select business_id, 'dol_5500', ein, null, plan_link from spon_b
union all
select business_id, source, rec_id, match_tier, null from rec_b;

-- Per business, each source's contribution. Picks are ordered on unique
-- keys, so unchanged input gives an unchanged file.
-- Only an EIN that registry rows share gives a business more than one row
-- (23,432 of 26.3M in October 2026). A single row passes through as it is:
-- aggregating every row ran out of memory at 26M rows (notes of spec 10).
-- The union is positional, so the two branches must list the same columns
-- in the same order; a column count that differs fails.
create or replace table reg_dup as
select business_id from reg_b group by business_id having count(*) > 1;

create or replace table reg_agg as
select business_id, source, state, registry_id, ein, name, address, city, zip5,
       coalesce(address_state, state) as address_state, address_kind,
       entity_type, status as registry_status, active,
       evidence_date(formed_date) as formed_date, naics,
       officers as registry_officers,
       columns(c -> regexp_matches(c, '^[a-z]{2}_') and c != 'as_of')
from reg_b anti join reg_dup using (business_id)
union all
select business_id,
       arg_min(source, (registry_id, source)) as source,
       arg_min(state, (registry_id, source)) as state,
       min(registry_id) as registry_id,
       min(ein) as ein,
       arg_min(name, (registry_id, source)) as name,
       arg_min(address, (registry_id, source)) as address,
       arg_min(city, (registry_id, source)) as city,
       arg_min(zip5, (registry_id, source)) as zip5,
       arg_min(coalesce(address_state, state), (registry_id, source))
           as address_state,
       arg_min(address_kind, (registry_id, source)) as address_kind,
       arg_min(entity_type, (registry_id, source)) as entity_type,
       arg_min(status, (registry_id, source)) as registry_status,
       arg_min(active, (registry_id, source)) as active,
       min(evidence_date(formed_date)) as formed_date,
       arg_min(naics, (registry_id, source)) as naics,
       arg_min(officers, (registry_id, source)) as registry_officers,
       -- extras: the columns a state module prefixed with its code
       arg_min(columns(c -> regexp_matches(c, '^[a-z]{2}_') and c != 'as_of'),
               (registry_id, source))
from reg_b semi join reg_dup using (business_id) group by business_id;

-- the names a record matched in tier 4, so the lookup can use that outlet
create or replace table t4_name as
select distinct business_id, zip5, norm_name as norm_dba_name
from rec_b where match_tier = 4
union
select distinct business_id, zip5, dba_norm_name
from rec_b where match_tier = 4 and dba_norm_name is not null;

-- the lookup trade name is the one a record matched in tier 4, else the
-- earliest; its extras come with it
create or replace table dba_agg as
select business_id,
       arg_min(source, k) as source,
       arg_min(state, k) as state,
       arg_min(registry_id, k) as registry_id,
       min(ein) as ein,
       arg_min(entity_type, k) as entity_type,
       list(distinct dba_name order by dba_name) as outlet_names,
       count(*) as outlet_count,
       min(evidence_date(first_seen_date)) as first_sales_date,
       arg_min(naics, k) filter (where naics is not null) as naics,
       arg_min({'name': dba_name, 'address': address, 'city': city, 'zip5': zip5},
               k) as outlet,
       arg_min(columns(c -> regexp_matches(c, '^[a-z]{2}_') and c != 'as_of'), k)
from (
    -- the whole row as text ends the key, so a tie is between identical rows
    select d.*,
           (t.business_id is null, coalesce(d.first_seen_date, date '9999-12-31'),
            coalesce(d.dba_name, ''), coalesce(d.address, ''), d.registry_id,
            d::VARCHAR) as k
    from dba_b d
    left join t4_name t using (business_id, zip5, norm_dba_name)
)
group by business_id;

-- the plan columns come from the sponsor that filed last
create or replace table spon_agg as
select b.business_id,
       arg_max(s.state, (s.date_received, s.ein)) as state,
       arg_max(s.ein, (s.date_received, s.ein)) as ein,
       arg_max(b.plan_link, (s.date_received, s.ein)) as plan_link,
       arg_max(s.sponsor_name, (s.date_received, s.ein)) as sponsor_name,
       arg_max(s.sponsor_dba_name, (s.date_received, s.ein))
           filter (where s.sponsor_dba_name is not null) as sponsor_dba_name,
       arg_max({'address': s.address, 'city': s.city, 'zip5': s.zip5,
                'state': s.state}, (s.date_received, s.ein))
           filter (where s.address is not null) as mailing,
       arg_max(s.phone, (s.date_received, s.ein)) filter (where s.phone is not null)
           as phone,
       arg_max(s.business_code, (s.date_received, s.ein))
           filter (where s.business_code is not null) as business_code,
       min(evidence_date(s.earliest_plan_eff_date)) as plan_eff_date,
       arg_max(s.signer_name, (s.date_received, s.ein)) as plan_signer_name,
       arg_max(s.signer_source, (s.date_received, s.ein)) as plan_signer_source,
       arg_max(s.plan_name, (s.date_received, s.ein)) as plan_name,
       arg_max(s.pension_codes, (s.date_received, s.ein)) as pension_codes,
       bool_or(s.ever_defined_benefit) as ever_defined_benefit,
       arg_max(s.active_participants, (s.date_received, s.ein))
           as active_participants,
       max(s.date_received) as plan_last_filed
from spon_b b join spon s using (ein)
group by b.business_id;

-- descriptive PPP fields come from the key with the largest total
create or replace table ppp_agg as
select b.business_id,
       arg_max(p.state, (p.ppp_total_approved, p.rec_id)) as state,
       arg_max(p.business_name, (p.ppp_total_approved, p.rec_id)) as business_name,
       arg_max(p.dba_norm_name, (p.ppp_total_approved, p.rec_id))
           filter (where p.dba_norm_name is not null) as dba_norm_name,
       arg_max({'address': p.address, 'city': p.city, 'zip5': p.zip5,
                'state': p.state}, (p.ppp_total_approved, p.rec_id))
           filter (where p.address is not null) as borrower,
       arg_max(p.business_type, (p.ppp_total_approved, p.rec_id)) as business_type,
       arg_max(p.business_age_description, (p.ppp_total_approved, p.rec_id))
           as business_age_description,
       list(distinct p.business_name order by p.business_name) as ppp_names,
       count(*) as ppp_key_count,
       sum(p.ppp_loan_count)::BIGINT as ppp_loan_count,
       sum(p.ppp_total_approved) as ppp_total_approved,
       min(p.ppp_first_loan_date) as ppp_first_loan_date,
       max(p.ppp_last_loan_date) as ppp_last_loan_date,
       max(p.jobs_reported) as jobs_reported,
       bool_or(p.nonprofit) as nonprofit,
       bool_or(p.charged_off) as charged_off,
       max(p.charge_off_date) as charge_off_date
from rec_b b join ppp_key p using (rec_id)
where b.source = 'ppp'
group by b.business_id;

create or replace table sba_agg as
select b.business_id,
       arg_max(k.state, (k.last_loan_date, k.rec_id)) as state,
       arg_max(k.business_name, (k.total_approved, k.rec_id)) as business_name,
       arg_max(k.naics, (k.last_loan_date, k.rec_id))
           filter (where k.naics is not null) as naics,
       arg_min(k.first_business_age, (k.first_loan_date, k.rec_id))
           as sba_first_business_age,
       list_sort(list_distinct(flatten(list(k.programs)))) as sba_programs,
       sum(k.loan_count)::BIGINT as sba_loan_count,
       sum(k.total_approved) as sba_total_approved,
       min(k.first_loan_date) as sba_first_loan_date,
       max(k.last_loan_date) as sba_last_loan_date,
       bool_or(k.charged_off) as sba_charged_off,
       max(k.charge_off_date) as charge_off_date
from rec_b b join sba_key k using (rec_id)
where b.source = 'sba'
group by b.business_id;

-- SAM: the descriptive fields come from the registration activated last;
-- the start date is the earliest
create or replace table sam_agg as
select b.business_id,
       arg_max({'uei': m.uei, 'cage': m.cage, 'status': m.registration_status,
                'expiration': m.expiration_date, 'structure': m.entity_structure,
                'legal_name': m.legal_name, 'dba_name': m.dba_name,
                'address': m.address_1, 'city': m.city, 'state': m.state,
                'zip5': m.zip5, 'naics': m.primary_naics},
               (m.activation_date, m.rec_id)) as latest,
       min(evidence_date(m.start_date)) as sam_start_date,
       max(m.activation_date) filter (where m.registration_status = 'A')
           as active_since,
       list(distinct poc order by poc) filter (where poc is not null)
           as sam_poc_names
from rec_b b
join sam_rec m using (rec_id)
cross join unnest([nullif(concat_ws(' ', m.gov_poc_first_name, m.gov_poc_last_name), ''),
                   nullif(concat_ws(' ', m.elec_poc_first_name, m.elec_poc_last_name), '')])
    as t(poc)
where b.source = 'sam'
group by b.business_id;

-- Each carrier with the business it landed in, joined once for the
-- aggregate, the names and the signals.
create or replace table fmcsa_b as
select b.business_id, c.*
from rec_b b join fmcsa_rec c using (rec_id)
where b.source = 'fmcsa';

-- FMCSA: the descriptive fields come from the carrier that filed its MCS-150
-- last; the add date is the earliest, and every officer is listed
create or replace table fmcsa_agg as
select c.business_id,
       arg_max({'dot': c.dot_number, 'status': c.status_code,
                'legal_name': c.legal_name, 'dba_name': c.dba_name,
                'address': c.phy_street, 'city': c.phy_city, 'state': c.phy_state,
                'zip5': c.zip5, 'email': c.email_address,
                'org': c.business_org_desc, 'classdef': c.classdef,
                'power_units': c.power_units, 'drivers': c.total_drivers},
               -- a carrier with no MCS-150 date still counts
               (coalesce(c.mcs150_date, date '0001-01-01'), c.dot_number))
           as latest,
       arg_max(c.phone, (coalesce(c.mcs150_date, date '0001-01-01'), c.dot_number))
           filter (where c.phone is not null) as phone,
       -- 1974-06-01 is the census's date for each of the 122,637 carriers
       -- entered before 1981 (no carrier has a later 1970s date), a load date
       -- rather than an add date, so it is no evidence of age
       min(evidence_date(nullif(c.add_date, date '1974-06-01'))) as fmcsa_add_date,
       list(distinct o order by o) filter (where o is not null) as fmcsa_officers,
       coalesce(bool_or(contains(c.classdef, 'FOR HIRE')), false) as for_hire
from fmcsa_b c
cross join unnest([c.company_officer_1, c.company_officer_2]) as t(o)
group by c.business_id;

-- the best tier any of the business's records used
create or replace table rec_agg as
select business_id, best.tier as match_tier, best.sim as match_similarity
from (
    select business_id,
           arg_min({'tier': match_tier, 'sim': match_similarity},
                   (match_tier, -match_similarity, rk)) as best
    from rec_b where match_tier is not null
    group by business_id
);

-- PPP industry: the most frequent code across the business's loans, latest
-- first
create or replace table ppp_naics as
select b.business_id,
       mode(l.naics order by l.date_approved desc, l.loan_number desc) as naics
from rec_b b join ppp_loan l using (norm_name, zip5)
where b.source = 'ppp'
group by b.business_id;

create or replace table src as
select business_id, list(distinct source order by source) as sources
from members group by business_id;

create or replace table names as
select business_id, list(distinct name order by name) as names
from (
    select business_id, name from reg_b
    union all select business_id, dba_name from dba_b
    union all
    select b.business_id, unnest([s.sponsor_name, s.sponsor_dba_name])
    from spon_b b join spon s using (ein)
    union all
    select b.business_id, l.borrower_name
    from rec_b b join ppp_loan l using (norm_name, zip5)
    where b.source = 'ppp'
    union all
    select b.business_id, l.borrower_name
    from rec_b b join sba_loan l using (norm_name, zip5)
    where b.source = 'sba'
    union all
    select b.business_id, unnest([m.legal_name, m.dba_name])
    from rec_b b join sam_rec m using (rec_id)
    where b.source = 'sam'
    union all
    select business_id, unnest([legal_name, dba_name]) from fmcsa_b
)
where name is not null
group by business_id;

-- Open status: the newest dated signal decides; on a tie, activity wins
-- over closure.
create or replace table signal as
select business_id, signal_on, kind, evidence || ' ' || strftime(signal_on, '%Y-%m-%d') as evidence
from (
    select business_id, as_of as signal_on, 'activity' as kind,
           source || ' good standing' as evidence
    from reg_b where active
    union all
    select business_id, coalesce(evidence_date(status_date), as_of), 'closure',
           source || ' not in good standing'
    from reg_b where not active
    union all
    select business_id, as_of, 'activity', source || ' listed'
    from dba_b where active
    union all
    select b.business_id, s.date_received, 'activity', 'form 5500 received'
    from spon_b b join spon s using (ein)
    union all
    select business_id, ppp_last_loan_date, 'activity', 'ppp loan approved'
    from ppp_agg
    union all
    select business_id, charge_off_date, 'closure', 'ppp loan charged off'
    from ppp_agg where charge_off_date is not null
    union all
    select business_id, sba_last_loan_date, 'activity', 'sba loan approved'
    from sba_agg
    union all
    select business_id, charge_off_date, 'closure', 'sba loan charged off'
    from sba_agg where charge_off_date is not null
    union all
    select business_id, active_since, 'activity', 'sam registration active'
    from sam_agg where active_since is not null
    union all
    select business_id, evidence_date(mcs150_date), 'activity',
           'fmcsa carrier active'
    from fmcsa_b where status_code = 'A'
    union all
    select business_id, coalesce(evidence_date(mcs150_date), as_of), 'closure',
           'fmcsa carrier inactive'
    from fmcsa_b where status_code = 'I'
)
where signal_on <= getvariable('run_date')::DATE
qualify row_number() over (
    partition by business_id
    order by signal_on desc, kind = 'activity' desc, evidence) = 1;

create or replace table naics as
select code, title
from read_csv(getvariable('naics_titles'), header=true, all_varchar=true);
-- three sectors span a range of two-digit prefixes in the Census list
create or replace temp macro naics_sector(c) as case left(c, 2)
    when '31' then '31-33' when '32' then '31-33' when '33' then '31-33'
    when '44' then '44-45' when '45' then '44-45'
    when '48' then '48-49' when '49' then '48-49'
    else left(c, 2) end;

-- Industry (decision 18), years (decision 11), lookup (decision 20) and open
-- status (decision 19). Addresses: FMCSA physical, SAM physical, trade name,
-- PPP, registry physical, then registry and sponsor mailing, then legal.
create or replace table picked as
select x.business_id, x.sources, n.names, r, d, s, p, b, g, sm, f,
       pn.naics as ppp_naics, sig,
       coalesce(
           if(f.latest.address is not null,
              {'address': f.latest.address, 'city': f.latest.city,
               'state': f.latest.state, 'zip5': f.latest.zip5,
               'source': 'fmcsa'}, null),
           if(sm.latest.address is not null,
              {'address': sm.latest.address, 'city': sm.latest.city,
               'state': sm.latest.state, 'zip5': sm.latest.zip5,
               'source': 'sam'}, null),
           if(d.outlet.address is not null,
              {'address': d.outlet.address, 'city': d.outlet.city,
               'state': d.state, 'zip5': d.outlet.zip5, 'source': d.source}, null),
           if(p.borrower is not null,
              {'address': p.borrower.address, 'city': p.borrower.city,
               'state': p.borrower.state, 'zip5': p.borrower.zip5,
               'source': 'ppp'}, null),
           if(r.address is not null and r.address_kind = 'physical',
              {'address': r.address, 'city': r.city, 'state': r.address_state,
               'zip5': r.zip5, 'source': r.source}, null),
           if(r.address is not null and r.address_kind = 'mailing',
              {'address': r.address, 'city': r.city, 'state': r.address_state,
               'zip5': r.zip5, 'source': r.source}, null),
           if(s.mailing is not null,
              {'address': s.mailing.address, 'city': s.mailing.city,
               'state': s.mailing.state, 'zip5': s.mailing.zip5,
               'source': 'dol_5500'}, null),
           if(r.address is not null,
              {'address': r.address, 'city': r.city, 'state': r.address_state,
               'zip5': r.zip5, 'source': r.source}, null)
       ) as lookup,
       coalesce(
           if(pn.naics is not null, {'code': pn.naics, 'source': 'ppp'}, null),
           if(s.business_code is not null,
              {'code': s.business_code, 'source': 'dol_5500'}, null),
           if(sm.latest.naics is not null,
              {'code': sm.latest.naics, 'source': 'sam'}, null),
           if(b.naics is not null, {'code': b.naics, 'source': 'sba'}, null),
           if(d.naics is not null, {'code': d.naics, 'source': d.source}, null),
           if(r.naics is not null, {'code': r.naics, 'source': r.source}, null),
           -- truck transportation, for for-hire carriers only
           if(f.for_hire, {'code': '484', 'source': 'fmcsa'}, null)
       ) as industry,
       least(r.formed_date, d.first_sales_date, s.plan_eff_date,
             sm.sam_start_date, evidence_date(b.sba_first_loan_date),
             p.ppp_first_loan_date, f.fmcsa_add_date) as oldest
-- src has exactly one row per business
from src x
left join names n using (business_id)
left join reg_agg r using (business_id)
left join dba_agg d using (business_id)
left join spon_agg s using (business_id)
left join ppp_agg p using (business_id)
left join sba_agg b using (business_id)
left join rec_agg g using (business_id)
left join sam_agg sm using (business_id)
left join fmcsa_agg f using (business_id)
left join ppp_naics pn using (business_id)
left join signal sig using (business_id);

create or replace table businesses as
select business_id,
       coalesce(r.state, d.state, s.state, p.state, b.state, sm.latest.state,
                f.latest.state) as state,
       sources,
       coalesce(r.registry_id, d.registry_id) as registry_id,
       coalesce(r.ein, d.ein, s.ein) as ein,
       names,
       coalesce(d.outlet.name, p.dba_norm_name, sm.latest.dba_name,
                f.latest.dba_name, s.sponsor_dba_name, p.business_name,
                sm.latest.legal_name, f.latest.legal_name, r.name,
                s.sponsor_name, b.business_name) as lookup_name,
       lookup.address as lookup_address,
       lookup.city as lookup_city,
       lookup.state as lookup_state,
       lookup.zip5 as lookup_zip5,
       lookup.source as lookup_address_source,
       coalesce(s.phone, f.phone) as phone,
       industry.code as naics,
       industry.source as naics_source,
       sector.title as sector,
       grp.title as industry_group,
       -- a code from an older NAICS edition gets its longest known prefix's title
       coalesce(t6.title, t5.title, grp.title, t3.title) as naics_title,
       date_sub('year', oldest, getvariable('run_date')::DATE) as years_in_business,
       oldest as oldest_evidence_date,
       case oldest
           when r.formed_date then 'formed'
           when d.first_sales_date then 'first_sales'
           when s.plan_eff_date then 'plan'
           when sm.sam_start_date then 'sam_start'
           when b.sba_first_loan_date then 'sba_loan'
           when p.ppp_first_loan_date then 'ppp_loan'
           when f.fmcsa_add_date then 'fmcsa_added'
       end as age_source,
       r.formed_date,
       d.first_sales_date,
       s.plan_eff_date,
       p.ppp_first_loan_date,
       case when sig.kind = 'closure' then 'likely_closed'
            when sig.signal_on >= getvariable('run_date')::DATE - interval 24 month
                then 'likely_open'
            else 'unknown'
       end as open_status,
       sig.evidence as open_evidence,
       r.registry_status,
       r.active,
       p.ppp_names,
       p.ppp_key_count,
       p.ppp_loan_count,
       p.ppp_total_approved,
       p.ppp_last_loan_date,
       p.jobs_reported,
       p.business_type,
       p.business_age_description,
       p.nonprofit,
       p.charged_off,
       b.sba_loan_count,
       b.sba_total_approved,
       b.sba_first_loan_date,
       b.sba_last_loan_date,
       b.sba_first_business_age,
       b.sba_programs,
       b.sba_charged_off,
       sm.latest.uei as sam_uei,
       sm.latest.cage as sam_cage,
       sm.sam_start_date,
       sm.latest.status as sam_registration_status,
       sm.latest.expiration as sam_expiration_date,
       sm.latest.structure as sam_entity_structure,
       sm.sam_poc_names,
       f.latest.dot as usdot_number,
       f.latest.status as fmcsa_status,
       f.fmcsa_add_date,
       f.fmcsa_officers,
       f.latest.org as fmcsa_business_org,
       f.latest.classdef as fmcsa_classdef,
       f.latest.power_units as fmcsa_power_units,
       f.latest.drivers as fmcsa_drivers,
       f.latest.email as fmcsa_email,
       g.match_tier,
       g.match_similarity,
       s.plan_link,
       coalesce(r.entity_type, d.entity_type) as entity_type,
       r.registry_officers,
       er.* exclude (business_id),
       d.outlet_names,
       d.outlet_count,
       ed.* exclude (business_id),
       s.plan_signer_name,
       s.plan_signer_source,
       s.plan_name,
       s.pension_codes,
       s.ever_defined_benefit,
       s.active_participants,
       s.plan_last_filed,
       getvariable('run_date')::DATE as run_date
from picked
-- extras pass through by pattern, never by name
left join (
    select business_id,
           columns(c -> regexp_matches(c, '^[a-z]{2}_') and c != 'as_of')
    from reg_agg
) er using (business_id)
left join (
    select business_id,
           columns(c -> regexp_matches(c, '^[a-z]{2}_') and c != 'as_of')
    from dba_agg
) ed using (business_id)
left join naics sector on sector.code = naics_sector(industry.code)
-- an industry group is a four-digit code; FMCSA's 484 is a subsector
left join naics grp on length(industry.code) >= 4
                   and grp.code = left(industry.code, 4)
left join naics t3 on t3.code = left(industry.code, 3)
left join naics t5 on t5.code = left(industry.code, 5)
left join naics t6 on t6.code = industry.code;
