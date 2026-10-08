-- cas.lua — Elsevier CAS (cas-sc) bridge for Quarto.
--
-- The rendered document must reproduce els-cas-templates/cas-sc-sample.tex
-- exactly, so everything here mirrors that sample. Three passes, in order:
--
--   0. Early    : cas-pre-ast.lua runs at the `pre-ast` entry point, before
--                  Quarto's normalize pipeline (crossref): it converts
--                  Table/Figure to the CAS markup below and turns
--                  @fig:, @tbl:, @eq:, ... into \protect\ref{...}. Everything
--                  here stays as a fallback for renders where that entry
--                  point is unavailable; caption_and_label() also understands
--                  the "{#id}" caption spelling crossref normalize produces.
--
--   1. Meta/Cite : journal.* -> cas-sc class options, bib style, natbib options
--                  (`authoryear,longnamesfirst`, as in the sample), short
--                  running head, and cross-references @fig:, @tbl:, @eq:,
--                  @sec:, ... -> \protect\ref{...}. Without this second part,
--                  `cite-method: natbib` turns cross-references into
--                  \citet citations (e.g. "\citet{fig:x}").
--
--   2. Floats    : pandoc Table/Figure -> the CAS markup used by the sample:
--                      \begin{table}[width=..,cols=..,pos=h]
--                        \caption{..}\label{tbl:x}
--                        \begin{tabular*}{\tblwidth}{@{} LLLL@{} } .. \end{tabular*}
--                      \end{table}
--                      \begin{figure} \centering \includegraphics[width=..] .. \end{figure}
--                  pandoc's default longtable/figure output does not match the
--                  template (column type L, \tblwidth, caption placement).
--
-- scripts/cas_fidelity.py checks the output against the official sample.

local stringify = pandoc.utils.stringify

-- --------------------------------------------------------------------------
-- 1. metadata
-- --------------------------------------------------------------------------

-- Options the official sample always uses (\documentclass[a4paper,fleqn]{cas-sc}).
local CAS_BASE_OPTIONS = { 'a4paper', 'fleqn' }

-- natbib options used by cas-sc-sample.tex: author-year plus longnamesfirst
-- (first citation of a work prints the full author list).
local NATBIB_OPTIONS = 'authoryear,longnamesfirst'

-- pandoc marshals a metadata *list* as a plain Lua table (no `.t` field) and a
-- metadata *string* as Inlines, so switch on pandoc.utils.type, not on `.t`.
local function to_string(value)
  if value == nil or type(value) == 'boolean' then
    return ''
  end
  if type(value) == 'string' then
    return value
  end
  local ok, s = pcall(stringify, value)
  if ok then
    return s
  end
  return ''
end

local function strings_of(value)
  local out = {}
  if value == nil then
    return out
  end
  if type(value) == 'table' and pandoc.utils.type(value) == 'List' then
    for _, v in ipairs(value) do
      local s = to_string(v)
      if s ~= '' then
        out[#out + 1] = s
      end
    end
    return out
  end
  local s = to_string(value)
  if s ~= '' then
    out[#out + 1] = s
  end
  return out
end

local function set_class_options(meta, options)
  local seen, list = {}, pandoc.MetaList({})
  for _, option in ipairs(options) do
    if option ~= '' and not seen[option] then
      seen[option] = true
      list[#list + 1] = pandoc.MetaString(option)
    end
  end
  meta['classoption'] = list
  return meta
end

-- Short running head for the page footer: "J.K. Krishnan et~al." in the sample.
local function author_family(author)
  local name = author.name
  if name == nil then
    return nil
  end
  if type(name) == 'string' then
    return name ~= '' and name or nil
  end
  if type(name) == 'table' then
    -- a normalized name map (Quarto/pandoc-citeproc style) ...
    if name.literal ~= nil or name.family ~= nil or name.given ~= nil then
      for _, key in ipairs({ 'literal', 'family', 'given' }) do
        local s = to_string(name[key])
        if s ~= '' then
          return s
        end
      end
      return nil
    end
    -- ... or plain Inlines
    local s = to_string(name)
    return s ~= '' and s or nil
  end
  local s = to_string(name)
  return s ~= '' and s or nil
end

local function author_list(meta)
  for _, key in ipairs({ 'by-author', 'author' }) do
    local authors = meta[key]
    if authors ~= nil and type(authors) == 'table' and #authors > 0 then
      return authors
    end
  end
  return nil
end

-- CAS \author[aff]{Name}[type=editor,auid=000,...]: assembled here because
-- pandoc templates cannot test "any of these keys is present". The order
-- mirrors cas-sc-sample.tex: type,auid,bioid,prefix,role (Krishnan) and
-- role,suffix (Hansen); orcid is appended last, as in the sample.
local CAS_AUTHOR_OPTIONS = { 'type', 'auid', 'bioid', 'prefix', 'role', 'suffix', 'style' }

-- \cormark[1] / \fnmark[1,3]: a number, a list of numbers or a bare `true`.
local function mark_value(value)
  if value == nil then
    return nil
  end
  if type(value) == 'boolean' then
    return value and '1' or nil
  end
  if type(value) == 'table' and pandoc.utils.type(value) == 'List' then
    local parts = {}
    for _, v in ipairs(value) do
      local s = to_string(v)
      if s ~= '' then
        parts[#parts + 1] = s
      end
    end
    if #parts == 0 then
      return nil
    end
    return table.concat(parts, ',')
  end
  local s = to_string(value)
  if s == '' or s == 'true' then
    return nil
  end
  return s
end

-- Derived per-author fields consumed by partials/before-body.tex:
--   cas-opts       -> the optional [key=value,...] argument of \author
--   cas-cormark    -> \cormark[...]   cas-fnmark -> \fnmark[...]
--   cas-url-style  -> \ead[url] vs \ead[URL] (the sample writes both)
--   credit         -> \credit{...}
--
-- Quarto's authors.lua turns every `attributes` value into the presence flag
-- the string 'true' (type=editor would arrive as type=true, which cas-sc
-- rejects with "key accepts only a fixed set of choices"), so all
-- value-bearing CAS options are written under the author's `cas:` key: an
-- unknown field that authors.lua stores verbatim in `metadata.cas`.
-- Simple fields (email, url, orcid) stay top-level and are read directly.
local function normalize_authors(meta)
  local authors = meta['by-author']
  if authors == nil or type(authors) ~= 'table' or pandoc.utils.type(authors) ~= 'List' then
    return meta
  end
  for _, author in ipairs(authors) do
    local md = type(author.metadata) == 'table' and author.metadata or {}
    local cas = type(md.cas) == 'table' and md.cas or {}
    local attrs = type(author.attributes) == 'table' and author.attributes or {}

    local function cas_value(key)
      local s = ''
      for _, source in ipairs({ cas, author, md, attrs }) do
        s = to_string(source[key])
        if s ~= '' and s ~= 'true' then
          return s
        end
      end
      return nil
    end

    local opts = {}
    for _, key in ipairs(CAS_AUTHOR_OPTIONS) do
      local s = cas_value(key)
      if s ~= nil then
        opts[#opts + 1] = key .. '=' .. s
      end
    end
    -- CAS wants the bare 16-digit ORCID inside the option list.
    local orcid = cas_value('orcid')
    if orcid ~= nil then
      orcid = orcid:gsub('https?://orcid%.org/', ''):gsub('/+$', '')
      if orcid ~= '' then
        opts[#opts + 1] = 'orcid=' .. orcid
      end
    end
    if #opts > 0 then
      author['cas-opts'] = pandoc.MetaString(table.concat(opts, ','))
    end

    local cormark = mark_value(cas.cormark or cas.corresponding)
      or mark_value(attrs.corresponding or attrs.cormark)
    if cormark ~= nil then
      author['cas-cormark'] = pandoc.MetaString(cormark)
    end
    local fnmark = mark_value(cas.fnmark or attrs.fnmark)
    if fnmark ~= nil then
      author['cas-fnmark'] = pandoc.MetaString(fnmark)
    end
    if author['credit'] == nil then
      local credit = cas_value('credit')
      if credit ~= nil then
        author['credit'] = pandoc.MetaString(credit)
      end
    end

    -- \ead[url] (Krishnan) vs \ead[URL] (Hansen, Rafeeq) in the sample.
    author['cas-url-style'] = pandoc.MetaString(cas_value('url-style') or 'url')

    -- Raw LaTeX name override for \author{...}. cas-common's \eadauthor
    -- splits given names on spaces and concatenates the initials WITHOUT a
    -- separator, so multi-part names need grouping braces to print
    -- "W. J. Hansen" as the sample does; a plain metadata string would be
    -- LaTeX-escaped ({ -> \{), so emit the value as a raw inline.
    local name_latex = cas_value('name-latex')
    if name_latex ~= nil then
      author['name-latex-raw'] = pandoc.MetaInlines({
        pandoc.RawInline('latex', name_latex),
      })
    end
  end
  return meta
end

local function set_short_authors(meta)
  local authors = author_list(meta)
  if authors == nil then
    return meta
  end
  local first = author_family(authors[1])
  if first == nil then
    return meta
  end
  -- The sample writes \shortauthors{J.K. Krishnan et~al.} with a real
  -- non-breaking space. A MetaString would be LaTeX-escaped (~ ->
  -- \textasciitilde), so build the head as Inlines with a raw "~".
  local inlines = { pandoc.Str(first) }
  if #authors > 1 then
    inlines[#inlines + 1] = pandoc.Str(' et')
    inlines[#inlines + 1] = pandoc.RawInline('latex', '~')
    inlines[#inlines + 1] = pandoc.Str('al.')
  end
  meta['short-authors'] = pandoc.MetaInlines(inlines)
  return meta
end

local function metadata_filter(meta)
  local options = {}
  for _, option in ipairs(CAS_BASE_OPTIONS) do
    options[#options + 1] = option
  end
  for _, option in ipairs(strings_of(meta['classoption'])) do
    options[#options + 1] = option
  end

  local journal = meta['journal']
  if journal ~= nil and type(journal) == 'table' then
    local formatting = to_string(journal['formatting'])
    if formatting ~= '' and formatting ~= 'none' then
      options[#options + 1] = formatting
    end
    if to_string(journal['cite-style']) == 'authoryear' then
      -- journal.biblio-style picks a shipped variant, e.g.
      -- cas-model2-names-etal (six authors, then "et al.").
      local style = to_string(journal['biblio-style'])
      meta['biblio-style'] = pandoc.MetaString(style ~= '' and style or 'cas-model2-names')
    end
  end

  -- Optional per-paper overrides (absent = the sample's behaviour):
  --   journal.equations: centered  -> drop fleqn (display equations centred)
  --   journal.natbib-options: "..." -> replace authoryear,longnamesfirst, e.g.
  --     "authoryear" when the journal wants "et al." from the first citation.
  local natbib_options = NATBIB_OPTIONS
  if journal ~= nil and type(journal) == 'table' then
    if to_string(journal['equations']) == 'centered' then
      local kept = {}
      for _, option in ipairs(options) do
        if option ~= 'fleqn' then
          kept[#kept + 1] = option
        end
      end
      options = kept
    end
    local custom = to_string(journal['natbib-options'])
    if custom ~= '' then
      natbib_options = custom
    end
  end

  meta = set_class_options(meta, options)
  meta['natbiboptions'] = pandoc.MetaString(natbib_options)
  meta = normalize_authors(meta)
  meta = set_short_authors(meta)
  return meta
end

-- --------------------------------------------------------------------------
-- 2. cross-references
-- --------------------------------------------------------------------------

local CROSSREF_PREFIXES = {
  fig = true, tbl = true, eq = true, sec = true, thm = true,
  lst = true, def = true, exm = true, prp = true, lem = true, cor = true,
  algo = true,
}

local function crossref_cites(cite)
  if type(FORMAT) ~= 'string' or FORMAT:find('latex', 1, true) == nil then
    -- docx: leave @fig-x/@tbl-x/@sec-x to Quarto's crossref, which renders
    -- them as text ("Figure 1"); raw LaTeX would be dropped by the writer.
    return nil
  end
  local refs = {}
  for _, citation in ipairs(cite.citations) do
    -- Quarto reserves both spellings: `@fig:x` (pandoc) and `@fig-x`
    -- (Quarto). Anything else is a real bibliography citation for natbib.
    local prefix = citation.id:match('^([%a]+)[:%-]')
    if prefix == nil or not CROSSREF_PREFIXES[prefix] then
      return nil -- a real bibliography citation: leave it to natbib
    end
  end
  for i, citation in ipairs(cite.citations) do
    if i > 1 then
      refs[#refs + 1] = ', '
    end
    -- \protect keeps the reference intact inside \caption{...} (the sample
    -- writes \protect\ref{tbl1} for the same reason) and is a no-op in text.
    refs[#refs + 1] = '\\protect\\ref{' .. citation.id .. '}'
  end
  return pandoc.RawInline('latex', table.concat(refs))
end

-- --------------------------------------------------------------------------
-- 3. floats
-- --------------------------------------------------------------------------

local function caption_blocks(caption)
  if caption == nil then
    return {}
  end
  local ok, long = pcall(function()
    return caption.long
  end)
  if ok and long ~= nil then
    return long
  end
  return {}
end

-- Render blocks to a single LaTeX line (captions and table cells cannot hold
-- paragraph breaks).
local function to_latex(blocks)
  if blocks == nil or #blocks == 0 then
    return ''
  end
  local ok, tex = pcall(pandoc.write, pandoc.Pandoc(blocks), 'latex')
  if not ok then
    return ''
  end
  tex = tex:gsub('\n\n+', ' ')
  tex = tex:gsub('\n', ' ')
  tex = tex:gsub('%s%s+', ' ')
  tex = tex:gsub('^%s+', '')
  tex = tex:gsub('%s+$', '')
  return tex
end

-- Caption text plus the float identifier. pandoc normally parses
-- ": caption {#tbl:x}" into the table attributes, but Quarto's crossref
-- normalize step moves the identifier into the caption as a literal
-- "{#tbl:x}" (LaTeX-escaped as \{\#tbl:one\}) and clears the attribute.
-- Accept both spellings, strip the literal and use it as the label.
local function caption_and_label(blocks, attr_id)
  local text = to_latex(blocks)
  local id = attr_id or ''
  local plain = text:match('%s*{(#[%w_%-:]+)}%s*$')
  local escaped = text:match('%s*\\%{\\#([%w_%-:]+)\\%}%s*$')
  local id_text = plain ~= nil and plain:sub(2) or escaped
  if id_text ~= nil then
    id = id_text
    text = text:gsub('%s*{(#[%w_%-:]+)}%s*$', '')
    text = text:gsub('%s*\\%{\\#([%w_%-:]+)\\%}%s*$', '')
    text = text:gsub('%s+$', '')
  end
  return text, id
end

local function align_to_column(alignment)
  if alignment == pandoc.AlignLeft then
    return 'L'
  elseif alignment == pandoc.AlignRight then
    return 'R'
  elseif alignment == pandoc.AlignCenter then
    return 'C'
  end
  return 'L' -- the sample writes L for every column
end

local function to_latex_row(row)
  local cells = {}
  for _, cell in ipairs(row.cells) do
    cells[#cells + 1] = to_latex(cell.contents)
  end
  if #cells == 0 then
    return nil
  end
  return table.concat(cells, ' & ') .. ' \\\\'
end

local function attr_or(attributes, key, default)
  local value = attributes and attributes[key]
  if value == nil or value == '' then
    return default
  end
  return value
end

local function table_filter(tbl)
  -- cas-tables.lua normally converted the table at pre-ast already; this is
  -- the fallback path. Skip non-LaTeX outputs so HTML keeps pandoc's tables.
  if type(FORMAT) ~= 'string' or FORMAT:find('latex', 1, true) == nil then
    return nil
  end
  local attributes = tbl.attributes or {}
  local attr_id = tbl.attr and tbl.attr.identifier or ''
  local caption, identifier = caption_and_label(caption_blocks(tbl.caption), attr_id)

  local columns = {}
  for _, colspec in ipairs(tbl.colspecs) do
    columns[#columns + 1] = align_to_column(colspec[1])
  end
  if #columns == 0 then
    return nil
  end

  local width = attr_or(attributes, 'width', '.9\\linewidth')
  local pos = attr_or(attributes, 'pos', 'h')
  local label = identifier ~= '' and ('\\label{' .. identifier .. '}') or ''

  local out = {}
  out[#out + 1] = '\\begin{table}[width=' .. width .. ',cols=' .. #columns
    .. ',pos=' .. pos .. ']'
  if caption ~= '' then
    out[#out + 1] = '\\caption{' .. caption .. '}' .. label
  elseif label ~= '' then
    out[#out + 1] = label
  end

  out[#out + 1] = '\\begin{tabular*}{\\tblwidth}{@{} ' .. table.concat(columns) .. '@{}}'
  out[#out + 1] = '\\toprule'

  for _, row in ipairs(tbl.head.rows) do
    local line = to_latex_row(row)
    if line ~= nil then
      out[#out + 1] = line
    end
  end
  if #tbl.head.rows > 0 then
    out[#out + 1] = '\\midrule'
  end

  for _, body in ipairs(tbl.bodies) do
    for _, row in ipairs(body.body) do
      local line = to_latex_row(row)
      if line ~= nil then
        out[#out + 1] = line
      end
    end
  end
  for _, row in ipairs(tbl.foot.rows) do
    local line = to_latex_row(row)
    if line ~= nil then
      out[#out + 1] = line
    end
  end

  out[#out + 1] = '\\bottomrule'
  out[#out + 1] = '\\end{tabular*}'
  out[#out + 1] = '\\end{table}'

  return pandoc.RawBlock('latex', table.concat(out, '\n'))
end

local function find_image(blocks)
  for _, block in ipairs(blocks) do
    if block.t == 'Plain' or block.t == 'Para' then
      for _, inline in ipairs(block.content) do
        if inline.t == 'Image' then
          return inline
        end
      end
    end
  end
  return nil
end

local function includegraphics_width(image)
  local width = image.attributes and image.attributes.width
  if width == nil or width == '' then
    -- the sample figure uses width=.9\textwidth
    return '.9\\textwidth'
  end
  if width:match('^%d*%.?%d+$') then
    return width .. '\\textwidth'
  end
  return width
end

local function figure_filter(fig)
  if type(FORMAT) ~= 'string' or FORMAT:find('latex', 1, true) == nil then
    return nil -- non-LaTeX outputs keep pandoc's figure rendering
  end
  local attr_id = fig.attr and fig.attr.identifier or ''
  local caption, identifier = caption_and_label(caption_blocks(fig.caption), attr_id)

  local image = find_image(fig.content)
  if image == nil then
    return nil -- no image: leave the figure to pandoc
  end

  local label = identifier ~= '' and ('\\label{' .. identifier .. '}') or ''

  local out = {}
  out[#out + 1] = '\\begin{figure}'
  out[#out + 1] = '\\centering'
  out[#out + 1] = '\\includegraphics[width=' .. includegraphics_width(image)
    .. ']{' .. image.src .. '}'
  if caption ~= '' then
    out[#out + 1] = '\\caption{' .. caption .. '}' .. label
  elseif label ~= '' then
    out[#out + 1] = label
  end
  out[#out + 1] = '\\end{figure}'

  return pandoc.RawBlock('latex', table.concat(out, '\n'))
end

-- --------------------------------------------------------------------------

return {
  {
    Meta = metadata_filter,
    Cite = crossref_cites,
  },
  {
    Table = table_filter,
    Figure = figure_filter,
  },
}
