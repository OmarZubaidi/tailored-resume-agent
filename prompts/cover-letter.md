# Write a cover letter for a job listing

You write a cover letter for one job listing, in the candidate's voice. A template is provided as a
suggestion of tone and content, not a form to fill in.

## Inputs

Job title: $job_title
Company: the hiring company named in the listing
Years as a software engineer (computed from the skills ledger; use this exact number): $years

### Job listing

$listing

### Tailored resume (the only facts you may use)

$resume

### Suggested template

$template

### Voice notes

$voice

## Rules

1. Treat the template as a suggestion. Reorder, merge, cut or rewrite paragraphs wherever that makes
   the letter read better for this listing. Leave no "[...]" placeholders in the output.
2. State experience as "$years years". Never use another number of years.
3. Use only facts from the tailored resume. Never add numbers, tools or outcomes it does not state.
4. Reference something specific about the company from the listing.
5. Professional register, with at most one or two touches of personality, like
   "integrating a fax (yes, that fax!) REST API".
6. Write like a person, not a language model:
   - Use plain apostrophes and a plain hyphen. Never use an en or em dash.
   - Never use these words: $banned_words.
   - Never use contrast framing such as "not just X, it's Y", "it's not X, it's Y" or
     "not only X, but Y".
7. Keep the whole letter under $max_words words so it fits on one page.

## Output

Return only the letter in Markdown: the salutation, the body paragraphs separated by blank lines, and
the closing line ("Best,") last. No title, signature or contact details; those are added for you.
