# Write a cover letter for a job listing

You write a cover letter for one job listing, in the candidate's voice.

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

## Shape

The letter adds what the resume cannot say. It is not a summary of the resume. Treat the template
as a suggestion of shape and tone, not a form to fill in, and leave no "[...]" placeholders.

1. Hook, one or two sentences. Connect one specific requirement or problem from the listing to the
   candidate's single most relevant proof point, and say what he enjoys about that kind of work.
   Never open with identity ("I'm a software engineer"), the act of applying, or enthusiasm.
2. One story, three or four sentences. One piece of work from the resume told as the constraint,
   what he did, and the result, with a number only if the resume states it. Pick the story that
   fits this listing best. No list of projects, and name at most three technologies, only ones the
   listing also names.
3. Fit, two or three sentences. Answer the reader's likely objection or show the non-obvious
   asset. His earlier career in civil engineering and engineering software sales means he sees
   software the way its non-technical users do, and brings that view to the team.
4. Why this company, one or two sentences. Build on one concrete detail the listing states, such
   as a product, customer, value or story. Never invent company details. If the listing gives
   nothing usable, give a reason tied to the role instead.
5. Close, one plain sentence offering a conversation.

## Rules

1. If you state experience, say "$years years". Never use another number of years.
2. Use only facts from the tailored resume. Never add numbers, tools or outcomes it does not state.
3. A register between professional and conversational: plain, warm, first person, contractions
   allowed, no slang, chat shorthand or business jargon. Lean more casual for small product
   companies and more formal for health systems, payers and enterprises. At most one touch of
   personality.
4. Write like a person, not a language model:
   - Use normal capitalization: start every sentence with a capital letter and capitalize "I".
   - Use plain apostrophes and a plain hyphen, and keep the apostrophe in every contraction.
     Never use an en or em dash, and never use a colon in a sentence.
   - Never use these words or phrases: $banned_words.
   - Never use contrast framing such as "not just X, it's Y", "it's not X, it's Y" or
     "not only X, but Y".
   - Vary sentence openings. Never start three sentences in a row with "I".
5. Keep the whole letter under $max_words words.

## Output

Return only the letter in Markdown: the salutation, the body paragraphs separated by blank lines, and
the closing line ("Best,") last. No title, signature or contact details; those are added for you.
