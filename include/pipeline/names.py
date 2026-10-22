# DuckDB macros for business-name matching; connect() registers them on every
# connection. norm_name: the name before any DBA, uppercased, punctuation and
# a leading THE and trailing entity words removed; a name that is only a DBA
# keeps the DBA. dba_name: the same for the part after the first DBA. Both
# return NULL for an empty result.
NAME_MACROS = r"""
-- the SBA names carry HTML entities: &AMP; is &, &#39; and &APOS; are '
create or replace macro name_unescape(s) as regexp_replace(
    replace(replace(replace(upper(s), '&AMP;', '&'), '&#39;', ''''), '&APOS;', ''''),
    '&#?[A-Z0-9]+;', ' ', 'g');
create or replace macro name_clean(s) as
    trim(regexp_replace(regexp_replace(regexp_replace(
        replace(name_unescape(s), '&', ' AND '),
        '[''’./]', '', 'g'),
        '[^A-Z0-9]', ' ', 'g'),
        ' +', ' ', 'g'));
create or replace macro name_finish(s) as
    nullif(trim(regexp_replace(
        ' ' || regexp_replace(trim(s), '^THE( |$)', ''),
        '( (INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|LLC|L L C|PLLC|LLP|LP|L P'
        || '|LTD|LIMITED|PC|P C|PA|P A))+$',
        '')), '');
create or replace macro dba_name(s) as
    name_finish(regexp_extract(name_clean(s), '\bDBA\b(.*)', 1));
create or replace macro norm_name(s) as coalesce(
    name_finish(regexp_replace(name_clean(s), '\bDBA\b.*', '')), dba_name(s));
"""
