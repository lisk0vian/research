-- cas-docx.lua — Word-native CAS front matter for the elsevier-cas DOCX format
-- (registered in the `docx:` block of _extension.yml; common filters such as
-- cas-pre-ast.lua / cas.lua are guarded to no-op outside LaTeX, so this is the
-- only CAS filter that acts on a .docx render).
--
-- It reproduces the front matter cas-sc prints in the PDF, in the same order,
-- so the DOCX paginates like the PDF (scripts/paper_parity.py measures it):
--
--   Highlights page  <- "Highlights", paper title, authors and one bullet per
--                       journal.highlights item, closed by a section break
--                       (the page is unnumbered in the PDF)
--   Title            <- meta.title (emitted here, after the highlights page)
--   Authors          <- given names grey, family names black, affiliation
--                       letters and * / fnmark superscripts, prefix/suffix/role
--   Affiliations     <- one line each, superscript letter, sample key order
--   ARTICLE INFO |   <- two-column table: keywords left, abstract right
--   ABSTRACT box        (geometry, rules and margins: tools/cas_docx_post.py)
--   front notes      <- real Word footnotes; cortext keeps the PDF's "*" and
--                       emails/URLs/ORCID get no mark (custom marks, applied
--                       by cas_docx_post.py from a private-use sentinel)
--
-- It also rasterizes .pdf/.eps figures to 300 dpi PNG (Word cannot embed
-- PostScript/PDF images); the source qmd keeps a single .pdf asset (Q4).
--
-- Everything below is format-guarded so the file can only affect docx output.

local function is_docx()
  return type(FORMAT) == 'string' and FORMAT:find('docx', 1, true) ~= nil
end

-- ---------------------------------------------------------------------------
-- metadata helpers (mirror cas.lua's access rules)
-- ---------------------------------------------------------------------------

local function text_of(value)
  if value == nil then
    return nil
  end
  local t = pandoc.utils.type(value)
  if t == 'string' then
    return value ~= '' and value or nil
  end
  if t == 'Inlines' or t == 'Blocks' or t == 'List' then
    local s = pandoc.utils.stringify(value)
    return s ~= '' and s or nil
  end
  if type(value) == 'string' then
    return value ~= '' and value or nil
  end
  local ok, s = pcall(pandoc.utils.stringify, value)
  if ok and type(s) == 'string' and s ~= '' then
    return s
  end
  return nil
end

local function cas_value(author, key)
  local md = type(author.metadata) == 'table' and author.metadata or {}
  local cas = type(md.cas) == 'table' and md.cas or {}
  local attrs = type(author.attributes) == 'table' and author.attributes or {}
  local sources = { cas, author, md, attrs }
  for _, source in ipairs(sources) do
    local s = text_of(source[key])
    if s ~= nil and s ~= 'true' then
      return s
    end
  end
  return nil
end

local function split_commas(value)
  local out = {}
  if value == nil then
    return out
  end
  for piece in tostring(value):gmatch('[^,]+') do
    out[#out + 1] = piece:gsub('^%s+', ''):gsub('%s+$', '')
  end
  return out
end

-- cas-sc prints "(M.E. Gamarra)" next to each email: given-name initials +
-- family name (its \eadauthor shortening).
local function short_name(full)
  local words = {}
  for word in full:gmatch('%S+') do
    words[#words + 1] = word
  end
  if #words < 2 then
    return full
  end
  local initials = {}
  for i = 1, #words - 1 do
    initials[#initials + 1] = words[i]:sub(1, 1) .. '.'
  end
  return table.concat(initials) .. ' ' .. words[#words]
end

local function aff_letter(number)
  local n = tonumber(number)
  if n == nil or n < 1 or n > 26 then
    return n ~= nil and tostring(n) or nil
  end
  return string.char(96 + n) -- 1 -> a
end

-- ---------------------------------------------------------------------------
-- footnote lookup (journal.corresponding / journal.author-notes)
-- ---------------------------------------------------------------------------

-- A note whose text starts with MARK_OPEN .. symbol .. MARK_CLOSE gets that
-- symbol (possibly empty) as its Word custom footnote mark instead of an
-- automatic number; cas_docx_post.py applies it and strips the sentinel.
local MARK_OPEN, MARK_CLOSE = '\u{E000}', '\u{E001}'

local function marked_note(symbol, inlines)
  local content = { pandoc.Str(MARK_OPEN .. symbol .. MARK_CLOSE) }
  for _, il in ipairs(inlines) do
    content[#content + 1] = il
  end
  return pandoc.Note(pandoc.Blocks({ pandoc.Para(content) }))
end

local function find_note(list, mark, symbol)
  for _, item in ipairs(list or {}) do
    if text_of(item.mark) == mark then
      local body = text_of(item.text)
      if body ~= nil then
        if symbol ~= nil then
          return marked_note(symbol, { pandoc.Str(body) })
        end
        return pandoc.Note(pandoc.Blocks({ pandoc.Para({ pandoc.Str(body) }) }))
      end
    end
  end
  return nil
end

local function notes_for_marks(list, prefix, marks)
  local notes = {}
  for _, mark in ipairs(split_commas(marks)) do
    local note = find_note(list, prefix .. mark)
    if note ~= nil then
      notes[#notes + 1] = note
    end
  end
  return notes
end

-- ---------------------------------------------------------------------------
-- block builders (pandoc applies custom-style Divs to every paragraph inside)
-- ---------------------------------------------------------------------------

local function styled_paragraph(style, inlines)
  return pandoc.Div(
    { pandoc.Para(inlines) },
    pandoc.Attr('', {}, { ['custom-style'] = style })
  )
end

-- marked_by_note: the corresponding-author footnote follows and prints the
-- star itself as its custom mark, so the superscript ends with a comma.
local function author_superscript(author, letters, marked_by_note)
  local parts = {}
  for _, letter in ipairs(letters) do
    parts[#parts + 1] = letter
  end
  local cormark = cas_value(author, 'cormark')
  local stars = tonumber(cormark)
  if marked_by_note then
    if #parts == 0 then
      return nil
    end
    return pandoc.Superscript({ pandoc.Str(table.concat(parts, ',') .. ',') })
  end
  if stars ~= nil and stars > 0 then
    parts[#parts + 1] = string.rep('\u{2217}', stars) -- ∗ x n, as in the PDF
  end
  local fnmark = cas_value(author, 'fnmark')
  for _, id in ipairs(split_commas(fnmark)) do
    parts[#parts + 1] = id
  end
  if #parts == 0 then
    return nil
  end
  return pandoc.Superscript({ pandoc.Str(table.concat(parts, ',')) })
end

local function affiliation_line(aff)
  local line = text_of(aff.name)
  if line == nil then
    return nil
  end
  local address = text_of(aff.address)
  local city = text_of(aff.city)
  local postal = text_of(aff['postal-code'])
  local region = text_of(aff.region)
  local country = text_of(aff.country)
  if address then
    line = line .. ', ' .. address
  end
  if region then
    if city then
      line = line .. ', ' .. city
    end
    if postal then
      line = line .. ', ' .. postal
    end
    line = line .. ', ' .. region
  else
    if postal then
      line = line .. ', ' .. postal
      if city then
        line = line .. ' ' .. city -- "1011 NX Amsterdam": no comma (sample)
      end
    elseif city then
      line = line .. ', ' .. city
    end
  end
  if country then
    line = line .. ', ' .. country
  end
  return line
end

-- ---------------------------------------------------------------------------
-- image rasterization (Word cannot embed .pdf/.eps)
-- ---------------------------------------------------------------------------

local function rasterize(img)
  if not is_docx() then
    return nil
  end
  local src = img.src or ''
  if not src:match('%.[pP][dD][fF]$') and not src:match('%.[eE][pP][sS]$') then
    return nil
  end
  local dir = os.getenv('TEMP') or os.getenv('TMP') or '.'
  local base = string.format('%s/cas-docx-%d-%d', (dir:gsub('\\', '/')),
                             os.time(), math.random(0, 999999))
  local cmd = string.format('pdftoppm -r 300 -f 1 -l 1 -png "%s" "%s"',
                            src, base)
  local ok = os.execute(cmd)
  local png = base .. '-1.png'
  local handle = io.open(png, 'rb')
  if handle == nil then
    png = base .. '-01.png'
    handle = io.open(png, 'rb')
  end
  if handle == nil then
    io.stderr:write('[cas-docx] could not rasterize ' .. src
      .. ' (is pdftoppm on PATH?); the image will be missing in the docx\n')
    return nil
  end
  handle:close()
  img.src = png
  -- a fractional unitless width (e.g. width=0.55, meaning 0.55\textwidth in
  -- the PDF) is read by the docx writer as a pixel count and rounds to 0,
  -- so the picture would vanish; drop it and let pandoc size the image from
  -- the rasterized PNG (cas_docx_post.py scales it to .9 text width).
  img.attributes.width = nil
  img.attributes.height = nil
  return img
end

-- ---------------------------------------------------------------------------
-- the front matter
-- ---------------------------------------------------------------------------

local GREY = '7F7F7F' -- cas-sc prints given names in black!50

local function raw(xml)
  return pandoc.RawInline('openxml', xml)
end

local function xml_text(s)
  return (s:gsub('&', '&amp;'):gsub('<', '&lt;'):gsub('>', '&gt;'))
end

-- a coloured run of plain text (names carry no markup)
local function colored_run(text, color)
  return raw('<w:r><w:rPr><w:color w:val="' .. color .. '"/></w:rPr>'
    .. '<w:t xml:space="preserve">' .. xml_text(text) .. '</w:t></w:r>')
end

local function author_names(by_author)
  local names = {}
  for _, author in ipairs(by_author or {}) do
    local name = text_of(author.name and author.name.literal)
    if name then
      names[#names + 1] = name
    end
  end
  return names
end

local function highlights_page(meta, journal, by_author)
  local highlights = journal.highlights
  if type(highlights) ~= 'table' or #highlights == 0 then
    return {}
  end
  local blocks = {
    styled_paragraph('HighlightsTitle', { pandoc.Str('Highlights') }),
  }
  if meta.title ~= nil then
    blocks[#blocks + 1] = styled_paragraph('HighlightsPaperTitle',
      pandoc.Inlines(meta.title))
  end
  local names = author_names(by_author)
  if #names > 0 then
    blocks[#blocks + 1] = styled_paragraph('HighlightsAuthors',
      { pandoc.Str(table.concat(names, ', ')) })
  end
  for _, item in ipairs(highlights) do
    local body = text_of(item)
    if body ~= nil then
      blocks[#blocks + 1] = styled_paragraph('Highlight', {
        pandoc.Str('\u{2022}'), raw('<w:r><w:tab/></w:r>'), pandoc.Str(body),
      })
    end
  end
  -- section break: cas_docx_post.py copies the body's page geometry into it;
  -- no header/footer references -> an unnumbered page, as in the PDF.
  blocks[#blocks + 1] = pandoc.RawBlock('openxml',
    '<w:p><w:pPr><w:pStyle w:val="CasSectionBreak"/><w:sectPr/></w:pPr></w:p>')
  return blocks
end

local function authors_paragraph(journal, by_author)
  local inlines = {}
  for i, author in ipairs(by_author) do
    if i > 1 then
      inlines[#inlines + 1] = pandoc.Str(i == #by_author and ' and ' or ', ')
    end
    local prefix = cas_value(author, 'prefix')
    local suffix = cas_value(author, 'suffix')
    local role = cas_value(author, 'role')
    local given = text_of(author.name and author.name.given)
    local family = text_of(author.name and author.name.family)
    local literal = text_of(author.name and author.name.literal)
    if prefix then
      inlines[#inlines + 1] = pandoc.Str(prefix .. ' ')
    end
    if given and family then
      inlines[#inlines + 1] = colored_run(given, GREY)
      inlines[#inlines + 1] = pandoc.Space()
      inlines[#inlines + 1] = pandoc.Str(family)
    elseif literal then
      inlines[#inlines + 1] = pandoc.Str(literal)
    end
    if suffix then
      inlines[#inlines + 1] = pandoc.Str(' ' .. suffix)
    end
    local letters = {}
    for _, aff in ipairs(author.affiliations or {}) do
      local letter = aff_letter(aff.number)
      if letter then
        letters[#letters + 1] = letter
      end
    end
    -- cortext: a real Word footnote whose custom mark is the PDF's star
    local cor_notes = {}
    local cormark = cas_value(author, 'cormark')
    for _, star in ipairs(split_commas(cormark)) do
      local stars = string.rep('\u{2217}', tonumber(star) or 1)
      local note = find_note(journal.corresponding, 'cor' .. star, stars)
      if note ~= nil then
        cor_notes[#cor_notes + 1] = note
      end
    end
    local sup = author_superscript(author, letters, #cor_notes > 0)
    if sup ~= nil then
      inlines[#inlines + 1] = sup
    end
    if role then
      inlines[#inlines + 1] = pandoc.Str(' (' .. role .. ')')
    end
    for _, note in ipairs(cor_notes) do
      inlines[#inlines + 1] = note
    end
    for _, note in ipairs(notes_for_marks(journal['author-notes'], 'fn',
                                           cas_value(author, 'fnmark'))) do
      inlines[#inlines + 1] = note
    end
  end
  return styled_paragraph('Author', inlines)
end

local function affiliation_paragraph(meta, journal, by_author)
  local inlines = {}
  for i, aff in ipairs(meta.affiliations or {}) do
    local line = affiliation_line(aff)
    if line ~= nil then
      if i > 1 then
        inlines[#inlines + 1] = pandoc.LineBreak()
      end
      local letter = aff_letter(aff.number)
      if letter then
        inlines[#inlines + 1] = pandoc.Superscript({ pandoc.Str(letter) })
      end
      inlines[#inlines + 1] = pandoc.Str(line)
    end
  end
  -- unmarked notes, as in the PDF: emails (behind the envelope the PDF
  -- prints), URLs, ORCIDs and nonumnote
  local emails, urls, orcids = {}, {}, {}
  for _, author in ipairs(by_author or {}) do
    local full = text_of(author.name and author.name.literal)
    local short = full and short_name(full) or nil
    local email = text_of(author.email)
    local url = text_of(author.url)
    local orcid = text_of(author.orcid)
    if email and short then
      emails[#emails + 1] = { email, short }
    end
    if url and short then
      urls[#urls + 1] = { url, short }
    end
    if orcid and short then
      orcids[#orcids + 1] = { orcid, short }
    end
  end
  local function listing(label, items, code)
    local out = { label }
    for i, item in ipairs(items) do
      if i > 1 then
        out[#out + 1] = pandoc.Str('; ')
      end
      out[#out + 1] = code and pandoc.Code(item[1]) or pandoc.Str(item[1])
      out[#out + 1] = pandoc.Str(' (' .. item[2] .. ')')
    end
    return out
  end
  if #emails > 0 then
    inlines[#inlines + 1] = marked_note('',
      listing(pandoc.Str('\u{2709} '), emails, true))
  end
  if #urls > 0 then
    inlines[#inlines + 1] = marked_note('',
      listing(pandoc.Str('URL(s): '), urls, true))
  end
  if #orcids > 0 then
    inlines[#inlines + 1] = marked_note('',
      listing(pandoc.SmallCaps({ pandoc.Str('ORCID(s): ') }), orcids, false))
  end
  local nonum = text_of(journal.nonumnote)
  if nonum ~= nil then
    inlines[#inlines + 1] = marked_note('', { pandoc.Str(nonum) })
  end
  if #inlines == 0 then
    return nil
  end
  return styled_paragraph('Affiliation', inlines)
end

-- ARTICLE INFO | ABSTRACT: keywords left (0.35 \textwidth), abstract right.
-- cas_docx_post.py finds the table by its AbstractTitle paragraphs (pandoc's
-- "Abstract Title" style; custom-style takes the style name) and sets
-- widths, rules and margins.
local function info_box(meta)
  local left = {
    styled_paragraph('Abstract Title', { pandoc.Str('ARTICLE INFO') }),
  }
  if type(meta.keywords) == 'table' and #meta.keywords > 0 then
    local inlines = { pandoc.Emph({ pandoc.Str('Keywords') }), pandoc.Str(':') }
    for _, kw in ipairs(meta.keywords) do
      local body = text_of(kw)
      if body ~= nil then
        inlines[#inlines + 1] = pandoc.LineBreak()
        inlines[#inlines + 1] = pandoc.Str(body)
      end
    end
    left[#left + 1] = styled_paragraph('Keywords', inlines)
  end
  local right = {
    styled_paragraph('Abstract Title', { pandoc.Str('ABSTRACT') }),
  }
  local abstract = meta.abstract
  if abstract ~= nil then
    local abs_blocks
    if pandoc.utils.type(abstract) == 'Blocks' then
      abs_blocks = abstract
    else
      abs_blocks = pandoc.Blocks({ pandoc.Para({ pandoc.Str(
        text_of(abstract) or '') }) })
    end
    right[#right + 1] = pandoc.Div(abs_blocks,
      pandoc.Attr('', {}, { ['custom-style'] = 'Abstract' }))
  end
  local row = pandoc.Row({ pandoc.Cell(pandoc.Blocks(left)),
                           pandoc.Cell(pandoc.Blocks(right)) })
  return pandoc.Table(
    pandoc.Caption(),
    { { pandoc.AlignLeft, 0.35 }, { pandoc.AlignLeft, 0.65 } },
    pandoc.TableHead(),
    { { attr = pandoc.Attr(), body = { row }, head = {}, row_head_columns = 0 } },
    pandoc.TableFoot())
end

local function front_matter(meta)
  local journal = type(meta.journal) == 'table' and meta.journal or {}
  local by_author = meta['by-author']
  local blocks = highlights_page(meta, journal, by_author)
  if meta.title ~= nil then
    blocks[#blocks + 1] = styled_paragraph('Title', pandoc.Inlines(meta.title))
  end
  if type(by_author) == 'table' and #by_author > 0 then
    blocks[#blocks + 1] = authors_paragraph(journal, by_author)
  end
  local aff = affiliation_paragraph(meta, journal, by_author)
  if aff ~= nil then
    blocks[#blocks + 1] = aff
  end
  blocks[#blocks + 1] = info_box(meta)
  return blocks
end

return {
  Pandoc = function(doc)
    if not is_docx() then
      return nil
    end
    local fm = front_matter(doc.meta)
    -- the blocks above replace pandoc's own Title/Author/Abstract
    doc.meta.title = nil
    doc.meta.author = nil
    doc.meta.abstract = nil
    for i = #fm, 1, -1 do
      table.insert(doc.blocks, 1, fm[i])
    end
    return doc
  end,
  Image = rasterize,
}
