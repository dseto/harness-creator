## [T-01] Template spec.md ganha secao Resumo executivo por padrao
- files: `skills/plan/references/contract-templates.md`
- verify: `python -c "text = open('skills/plan/references/contract-templates.md', encoding='utf-8').read(); assert '## Resumo executivo' in text; assert text.index('## Resumo executivo') < text.index('## Escopo')"`
