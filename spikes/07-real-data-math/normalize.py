"""Recover complete mathematical answers from narrowly defined formatting errors.

No model calls; no changes to equations, numbers, code, or raw responses.
"""
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    for folder in (ROOT/"rescue-results").glob("*/mimo-v2.6-pro"):
        status_path = folder/"status.json"
        if not status_path.exists():
            continue
        status = json.loads(status_path.read_text())
        if status.get("completed") or status.get("answer_recovered"):
            continue
        calls = [p for p in folder.glob("call-*.json") if not p.name.endswith(".request.json")]
        if not calls:
            continue
        raw = json.loads(sorted(calls)[-1].read_text())["response"]
        choice = (raw.get("choices") or [{}])[0]
        if choice.get("finish_reason") != "stop":
            continue
        text = (choice.get("message") or {}).get("content")
        if not isinstance(text,str):
            continue
        repairs = []
        try:
            answer = json.loads(text)
        except json.JSONDecodeError:
            try:
                answer = json.loads(text+"}")
                repairs.append("Appended one missing outer JSON closing brace")
            except json.JSONDecodeError:
                fences = re.findall(r"```json\s*\n([\s\S]*?)\n```", text)
                if len(fences) != 1:
                    continue
                fenced = fences[0]
                quote_repairs = 0
                try:
                    while True:
                        try:
                            answer = json.loads(fenced)
                            break
                        except json.JSONDecodeError as error:
                            if error.msg != "Invalid \\escape" or fenced[error.pos:error.pos+2] != "\\'":
                                raise
                            # JSON does not escape apostrophes. Decode the intended
                            # literal quote without changing the submitted Python.
                            fenced = fenced[:error.pos] + fenced[error.pos+1:]
                            quote_repairs += 1
                    repairs.append("Extracted the single complete JSON fence after the model's prose preamble")
                    if quote_repairs:
                        repairs.append(f"Removed {quote_repairs} invalid JSON apostrophe escapes")
                except json.JSONDecodeError:
                    continue
        if isinstance(answer.get("empirical"),dict):
            for key in ["limitations","conclusion"]:
                if key not in answer and key in answer["empirical"]:
                    answer[key] = answer["empirical"].pop(key)
                    repairs.append("Moved existing "+key+" from empirical to the required outer level")
        if not all(key in answer for key in ["derivation","python","empirical","limitations","conclusion"]):
            continue
        if not isinstance(answer["python"],str):
            continue
        ast.parse(answer["python"])
        (folder/"final-normalized.json").write_text(json.dumps(answer,ensure_ascii=False,indent=2))
        (folder/"submitted.py").write_text(answer["python"]+"\n")
        (folder/"normalization.json").write_text(json.dumps({"raw_response_unchanged":True,
            "repairs":repairs,"mathematics_numbers_and_python_unchanged":True},indent=2))
        status.update({"answer_recovered":True,"normalization_artifact":"normalization.json",
                       "normalized_final":"final-normalized.json"})
        status_path.write_text(json.dumps(status,indent=2))
        print(folder.relative_to(ROOT),repairs)


if __name__ == "__main__":
    main()
