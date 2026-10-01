-- cas-docx.lua — Word-native CAS front matter for the elsevier-cas DOCX format
-- (registered in the `docx:` block of _extension.yml; common filters such as
-- cas-pre-ast.lua / cas.lua are guarded to no-op outside LaTeX, so this is the
-- only CAS filter that acts on a .docx render).
--
-- It reproduces what cas-sc prints in the PDF, in Word-native constructs:
--
--   Title            <- pandoc emits meta.title itself (Title style)
--   Authors          <- paragraph with affiliation letters, * / fnmark
--                       superscripts, prefix/suffix/role, and real Word
--                       footnotes for cortext/fntext (auto-numbered marks
--                       replace the printed glyphs — Q6b: notes carry text
--                       only, no thumbnail icons)
--   Affiliations     <- one line each, superscript letter, sample key order
--   ABSTRACT box     <- AbstractTitle (caps, rules) + Abstract paragraphs
--   Highlights       <- title + one Highlight-styled paragraph per item
--   Keywords         <- italic "Keywords:" label + one line per keyword
--   emails/URLs/ORCID/nonumnote -> Word footnotes on the affiliation line
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

local function find_note(list, mark)
  for _, item in ipairs(list or {}) do
    if text_of(item.mark) == mark then
      local body = text_of(item.text)
      if body ~= nil then
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

local function author_superscript(author, letters)
  local parts = {}
  for _, letter in ipairs(letters) do
    parts[#parts + 1] = letter
  end
  local cormark = cas_value(author, 'cormark')
  local stars = tonumber(cormark)
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
  return img
end

-- ---------------------------------------------------------------------------
-- the front matter
-- ---------------------------------------------------------------------------

local function front_matter(meta)
  local blocks = {}
  local journal = type(meta.journal) == 'table' and meta.journal or {}
  local by_author = meta['by-author']
  local frontnotes = {} -- footnotes that live on the affiliation line

  -- 1. authors ---------------------------------------------------------------
  if type(by_author) == 'table' and #by_author > 0 then
    local inlines = {}
    for i, author in ipairs(by_author) do
      if i > 1 then
        inlines[#inlines + 1] = pandoc.Str(i == #by_author and ' and ' or ', ')
      end
      local prefix = cas_value(author, 'prefix')
      local suffix = cas_value(author, 'suffix')
      local role = cas_value(author, 'role')
      local name = text_of(author.name and author.name.literal)
      if name then
        if prefix then
          inlines[#inlines + 1] = pandoc.Str(prefix .. ' ')
        end
        inlines[#inlines + 1] = pandoc.Str(name)
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
        local sup = author_superscript(author, letters)
        if sup ~= nil then
          inlines[#inlines + 1] = sup
        end
        if role then
          inlines[#inlines + 1] = pandoc.Str(' (' .. role .. ')')
        end
        -- cortext/fntext become real Word footnotes attached to the name
        local cormark = cas_value(author, 'cormark')
        for _, star in ipairs(split_commas(cormark)) do
          local note = find_note(journal.corresponding, 'cor' .. star)
          if note ~= nil then
            inlines[#inlines + 1] = note
          end
        end
        for _, note in ipairs(notes_for_marks(journal['author-notes'], 'fn',
                                               cas_value(author, 'fnmark'))) do
          inlines[#inlines + 1] = note
        end
      end
    end
    if #inlines > 0 then
      blocks[#blocks + 1] = styled_paragraph('Author', inlines)
    end

    -- nonumnote (unnumbered in the PDF; Word numbers every footnote)
    local nonum = text_of(journal.nonumnote)
    if nonum ~= nil then
      frontnotes[#frontnotes + 1] = pandoc.Note(
        pandoc.Blocks({ pandoc.Para({ pandoc.Str(nonum) }) }))
    end
  end

  -- 2. affiliations + email/url/orcid footnotes ------------------------------
  local affiliations = meta.affiliations
  local affil_inlines = {}
  if type(affiliations) == 'table' then
    for i, aff in ipairs(affiliations) do
      local line = affiliation_line(aff)
      if line ~= nil then
        if i > 1 then
          affil_inlines[#affil_inlines + 1] = pandoc.LineBreak()
        end
        local letter = aff_letter(aff.number)
        if letter then
          affil_inlines[#affil_inlines + 1] =
            pandoc.Superscript({ pandoc.Str(letter) })
          affil_inlines[#affil_inlines + 1] = pandoc.Space()
        end
        affil_inlines[#affil_inlines + 1] = pandoc.Str(line)
      end
    end
  end

  if type(by_author) == 'table' then
    local emails, urls, orcids = {}, {}, {}
    for _, author in ipairs(by_author) do
      local full = text_of(author.name and author.name.literal)
      local short = full and short_name(full) or nil
      local email = text_of(author.email)
      local url = text_of(author.url)
      local orcid = text_of(author.orcid)
      if email and short then
        emails[#emails + 1] = string.format('%s (%s)', email, short)
      end
      if url and short then
        urls[#urls + 1] = string.format('%s (%s)', url, short)
      end
      if orcid and short then
        orcids[#orcids + 1] = string.format('%s (%s)', orcid, short)
      end
    end
    if #emails > 0 then
      frontnotes[#frontnotes + 1] = pandoc.Note(pandoc.Blocks({
        pandoc.Para({ pandoc.Str('Emails: ' .. table.concat(emails, '; ')) }),
      }))
    end
    if #urls > 0 then
      frontnotes[#frontnotes + 1] = pandoc.Note(pandoc.Blocks({
        pandoc.Para({ pandoc.Str('URLs: ' .. table.concat(urls, '; ')) }),
      }))
    end
    if #orcids > 0 then
      frontnotes[#frontnotes + 1] = pandoc.Note(pandoc.Blocks({
        pandoc.Para({ pandoc.Str('ORCID(s): ' .. table.concat(orcids, '; ')) }),
      }))
    end
  end

  if #affil_inlines > 0 or #frontnotes > 0 then
    for _, note in ipairs(frontnotes) do
      affil_inlines[#affil_inlines + 1] = note
    end
    blocks[#blocks + 1] = styled_paragraph('Affiliation', affil_inlines)
  end

  -- 3. abstract (ABSTRACT label with the sample's rules) ---------------------
  local abstract = meta.abstract
  if abstract ~= nil then
    blocks[#blocks + 1] = styled_paragraph('AbstractTitle',
                                           { pandoc.Str('ABSTRACT') })
    local abs_blocks
    if pandoc.utils.type(abstract) == 'Blocks' then
      abs_blocks = abstract
    else
      abs_blocks = pandoc.Blocks({ pandoc.Para({ pandoc.Str(
        text_of(abstract) or '') }) })
    end
    blocks[#blocks + 1] = pandoc.Div(abs_blocks,
      pandoc.Attr('', {}, { ['custom-style'] = 'Abstract' }))
  end

  -- 4. highlights ------------------------------------------------------------
  local highlights = journal.highlights
  if type(highlights) == 'table' and #highlights > 0 then
    blocks[#blocks + 1] = styled_paragraph('HighlightsTitle',
                                           { pandoc.Str('Highlights') })
    for _, item in ipairs(highlights) do
      local body = text_of(item)
      if body ~= nil then
        blocks[#blocks + 1] = styled_paragraph('Highlight', {
          pandoc.Str('\u{2022}\u{00A0}'),
          pandoc.Str(body),
        })
      end
    end
  end

  -- 5. keywords (sample: italic label, one keyword per line) -----------------
  if type(meta.keywords) == 'table' and #meta.keywords > 0 then
    local inlines = { pandoc.Emph({ pandoc.Str('Keywords:') }) }
    for _, kw in ipairs(meta.keywords) do
      local body = text_of(kw)
      if body ~= nil then
        inlines[#inlines + 1] = pandoc.LineBreak()
        inlines[#inlines + 1] = pandoc.Str(body)
      end
    end
    blocks[#blocks + 1] = styled_paragraph('Keywords', inlines)
  end

  return blocks
end

return {
  Pandoc = function(doc)
    if not is_docx() then
      return nil
    end
    local fm = front_matter(doc.meta)
    -- let pandoc emit the Title from meta.title, but suppress its own plain
    -- Author/Abstract blocks: we render them CAS-style above.
    doc.meta.author = nil
    doc.meta.abstract = nil
    for i = #fm, 1, -1 do
      table.insert(doc.blocks, 1, fm[i])
    end
    return doc
  end,
  Image = rasterize,
}
