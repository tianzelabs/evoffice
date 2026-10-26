"""Compact collective context for the manager; all heavy data stays outside prompts."""
import json
from pathlib import Path

from agents.common.experience import render_experience


def collective_briefing(office, state_dir: Path | None = None) -> str:
    parts=[]
    try:
        experience=office.experience()
        report=render_experience(experience)
        parts.append(report)
        if state_dir:
            state_dir.mkdir(parents=True,exist_ok=True)
            (state_dir/'collective-experience.json').write_text(json.dumps(experience,ensure_ascii=False,indent=2))
            (state_dir/'collective-experience.md').write_text(report+'\n')
    except Exception as error:
        parts.append(f'Historical experience unavailable: {type(error).__name__}: {str(error)[:150]}')
    try:
        knowledge=office.knowledge(limit=5)
        parts.append('COLLECTIVE KNOWLEDGE (attributed evidence/opinion, not votes):')
        for row in knowledge:
            p=row['payload']
            parts.append(f"#{row['id']} {row['actor']} [{p['perspective']}/{p['kind']}/{p['provenance']}] "
                         f"{p['topic']}: {p['claim'][:300]} refs={p['evidence'][:2]}")
        if not knowledge:parts.append('No contributions yet; append useful new evidence, not repeated summaries.')
    except Exception as error:
        parts.append(f'Collective knowledge unavailable: {type(error).__name__}: {str(error)[:150]}')
    return '\n'.join(parts)
