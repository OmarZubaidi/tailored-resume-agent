# Extract a job listing's hard requirements

Read one job listing and list what it requires. Do not judge the candidate.

## Job listing

$listing

## Rules

1. `years_required`: the minimum years of professional experience the listing requires, as a whole
   number, or null if it states none. Use the lowest number if it gives a range.
2. `required_skills`: hard skills listed as required (languages, frameworks, tools, platforms,
   standards). Leave out "preferred", "nice to have" and "bonus" items. Use the listing's spelling.
3. `other_requirements`: required items that are not skills, such as a degree or a domain.

## Output

Return only JSON, no prose:

```json
{
  "years_required": 3,
  "required_skills": ["TypeScript", "React", "AWS"],
  "other_requirements": ["Bachelor's degree in Computer Science or equivalent experience"]
}
```
