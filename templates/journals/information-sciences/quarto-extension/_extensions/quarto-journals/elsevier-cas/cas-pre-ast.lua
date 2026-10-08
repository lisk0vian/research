-- cas-pre-ast.lua — early CAS pass, run at the `pre-ast` filter entry point
-- (see _extension.yml), BEFORE any Quarto filter has touched the document.
--
-- Why early: Quarto's normalize pipeline (crossref) rewrites floats and
-- references before the default `pre-quarto` entry point where cas.lua runs:
--
--   * Tables with an identifier come back with the identifier moved into the
--     caption as a literal "{#tbl:x}" and the attribute cleared;
--   * `{#tbl-x}` / `{#fig-x}` (Quarto-native ids) are wrapped in a
--     FloatRefTarget whose render pass — running AFTER our default filter —
--     would wrap our raw \begin{table}/\begin{figure} in a second float
--     environment (an error: cas-sc floats do not nest);
--   * `@tbl-x` / `@fig-x` references are resolved by crossref during
--     normalize; with the float already converted above, the target is
--     "missing" and crossref prints a bold `?`.
--
-- Converting tables, figures and crossref-style references here — before any
-- Quarto filter runs — sees the pristine reader AST (identifier in the
-- attribute, caption clean) and removes the float before crossref touches
-- it, so every id spelling (`{#tbl:x}` and `{#tbl-x}`) behaves the same:
-- \label where we put it, \protect\ref where the author asked for it.
--
-- Keep captions plain (no `{{< shortcode >}}`): shortcodes expand later.
-- Real bibliography citations are left for natbib (cite-method: natbib).
--
-- This file duplicates the small helpers of cas.lua on purpose: filter
-- files are loaded in isolated environments, so they cannot share locals,
-- and cas.lua keeps its own copies as a fallback.

-- local replacement for _quarto.format.isLatexOutput(): the `_quarto`
-- namespace does not exist yet at the pre-ast entry point, but FORMAT is
-- provided by pandoc itself.
local function is_latex_output()
  return type(FORMAT) == 'string' and FORMAT:find('latex', 1, true) ~= nil
end

-- --------------------------------------------------------------------------
-- shared helpers (mirrors cas.lua)
-- --------------------------------------------------------------------------

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

-- Caption text plus the float identifier. pandoc normally parses
-- ": caption {#tbl:x}" into the table attributes; the strip below is a
-- belt-and-braces fallback if a literal "{#tbl:x}" survives in the text
-- (same acceptance rules as cas.lua's caption_and_label).
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

-- cas-common.sty defines L/C/R as `\extracolsep{\fill}` + l/c/r, and `l` does
-- NOT wrap: a cell of prose is one long line and the table runs out of the
-- column (Elsevier's own sample fits because its cells are short). Emit
-- `p{}` columns of an equal share of \tblwidth so long cells wrap, keeping the
-- alignment pandoc inferred from the pipe table.
local function column_spec(alignment, ncols)
  local decl = alignment == pandoc.AlignRight and '\\raggedleft'
    or alignment == pandoc.AlignCenter and '\\centering' or '\\raggedright'
  local share = '\\dimexpr(\\tblwidth-' .. 2 * (ncols - 1) .. '\\tabcolsep)/' .. ncols .. '\\relax'
  return '>{' .. decl .. '\\arraybackslash}p{' .. share .. '}'
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

-- --------------------------------------------------------------------------
-- docx table notes: a [..]{.note} span inside a table caption becomes its
-- own paragraph right after the table. Word has no \par note block, and the
-- raw LaTeX cas-pre-ast emits for the PDF would simply be dropped by the
-- docx writer, so the note travels as text with a private-use sentinel that
-- cas_docx_post.py strips, styles and folds back into the float.
-- --------------------------------------------------------------------------

local NOTE_MARK = '\u{E010}'

local function docx_table_notes(tbl)
  if is_latex_output() then
    return nil
  end
  local note = pandoc.List()
  local kept = pandoc.List()
  local changed = false
  for _, block in ipairs(caption_blocks(tbl.caption)) do
    if block.t == 'Plain' or block.t == 'Para' then
      local out = pandoc.List()
      for _, inline in ipairs(block.content) do
        if inline.t == 'Span' and inline.classes:includes('note') then
          changed = true
          for _, x in ipairs(inline.content) do
            note:insert(x)
          end
        else
          out:insert(inline)
        end
      end
      kept:insert(pandoc[block.t](out))
    else
      kept:insert(block)
    end
  end
  if not changed or #note == 0 then
    return nil
  end
  local short = nil
  local ok, s = pcall(function() return tbl.caption.short end)
  if ok then
    short = s
  end
  tbl.caption = pandoc.Caption(kept, short)
  local inlines = pandoc.List({ pandoc.Str(NOTE_MARK) })
  for _, x in ipairs(note) do
    inlines:insert(x)
  end
  return { tbl, pandoc.Para(inlines) }
end

local function attr_or(attributes, key, default)
  local value = attributes and attributes[key]
  if value == nil or value == '' then
    return default
  end
  return value
end

-- --------------------------------------------------------------------------
-- tables (mirrors cas.lua's table_filter)
-- --------------------------------------------------------------------------

-- pandoc Table -> the CAS markup used by cas-sc-sample.tex:
--   \begin{table}[width=..,cols=..,pos=h]
--     \caption{..}\label{tbl:x}
--     \begin{tabular*}{\tblwidth}{@{} LRCR@{}} ... \end{tabular*}
--   \end{table}
local function table_filter(tbl)
  local docx = docx_table_notes(tbl)
  if docx ~= nil then
    return docx
  end
  if not is_latex_output() then
    return nil -- HTML/other formats keep pandoc's own table rendering
  end

  local attributes = tbl.attributes or {}
  local attr_id = tbl.attr and tbl.attr.identifier or ''
  local caption, identifier = caption_and_label(caption_blocks(tbl.caption), attr_id)

  local columns = {}
  for _, colspec in ipairs(tbl.colspecs) do
    columns[#columns + 1] = column_spec(colspec[1], #tbl.colspecs)
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

-- --------------------------------------------------------------------------
-- figures (mirrors cas.lua's figure_filter)
-- --------------------------------------------------------------------------

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
  if not is_latex_output() then
    return nil
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
-- cross-references (mirrors cas.lua's crossref_cites)
-- --------------------------------------------------------------------------

local CROSSREF_PREFIXES = {
  fig = true, tbl = true, eq = true, sec = true, thm = true,
  lst = true, def = true, exm = true, prp = true, lem = true, cor = true,
  algo = true,
}

-- Quarto reserves both spellings: `@fig:x` (pandoc style) and `@fig-x`
-- (Quarto style). A citation id without a recognized prefix is a real
-- bibliography citation and belongs to natbib.
local function is_crossref_id(id)
  local prefix = id:match('^([%a]+)[:%-]')
  return prefix ~= nil and CROSSREF_PREFIXES[prefix] or nil
end

local function crossref_cites(cite)
  if not is_latex_output() then
    return nil
  end
  local refs = {}
  for _, citation in ipairs(cite.citations) do
    if is_crossref_id(citation.id) == nil then
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

return {
  Table = table_filter,
  Figure = figure_filter,
  Cite = crossref_cites,
}
