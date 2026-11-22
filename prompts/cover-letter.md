# Write a cover letter for a job listing

You fill in a cover letter template for one job listing, in the candidate's voice.

## Inputs

Job title: $job_title
Company: the hiring company named in the listing
Years as a software engineer (computed from the skills ledger; use this exact number): $years

### Job listing

$listing

### Tailored resume (the only facts you may use)

$resume

### Cover letter template

$template

### Voice notes

$voice

## Rules

1. Keep the template's structure and paragraph order. Replace every bracketed placeholder; leave no
   "[...]" in the output.
2. State experience as "$years years". Never use another number of years.
3. Use only facts from the tailored resume. Never add numbers, tools or outcomes it does not state.
4. Reference something specific about the company from the listing.
5. Professional register, with at most one or two touches of personality, like
   "integrating a fax (yes, that fax!) REST API".
6. Use plain apostrophes and a plain hyphen. Never use an en or em dash.

## Output

Return only the letter in Markdown: the salutation, the body paragraphs separated by blank lines, and
the closing line ("Best,") last. No title, signature or contact details; those are added for you.
