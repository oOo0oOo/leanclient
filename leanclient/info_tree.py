import re

# Pre-compile regex patterns
node_pattern = re.compile(r"^(\s*)• (.*)$")
type_pattern = re.compile(r"^\[(?P<type>.*)\]")
range_pattern = re.compile(
    r"@ ⟨(?P<start_line>\d+), (?P<start_char>\d+)⟩(?P<start_syn>†?)"
    r"-⟨(?P<end_line>\d+), (?P<end_char>\d+)⟩(?P<end_syn>†?)"
)
elaborator_pattern = re.compile(r"@ ([A-Za-z0-9_.«»]+)$")


def parse_info_tree(info_tree_str: str) -> dict:
    """Parses a Lean info tree string into a nested Python dictionary structure.

    Attention:
        This function is experimental and may change in future versions.

    Processes the textual representation of a Lean info tree. It currently supports extracting:

    * Indentation-based hierarchy
    * Node text
    * Node type
    * Source code range
    * Elaborator information
    * Additional metadata
    * Goal states for tactic nodes

    Note:
        Given the complexity of Lean's info trees, this function only covers a small subset of structures.
        Further manual parsing might be required.

    Example Output:

    .. code-block:: python

        {'text': '[Command] @ ⟨19, 0⟩-⟨19, 52⟩ @ Lean.Elab.Command.elabDeclaration', 'children': [{'text': '[Term] Nat : Type @ ⟨19, 24⟩-⟨19, 27⟩ @ Lean.Elab.Term.elabIdent', 'children': [{'text': '[Completion-Id] Nat : some Sort.{?_uniq.131} @ ⟨19, 24⟩-⟨19, 27⟩', 'children': [{'text': '[Term] Nat : Type @ ⟨19, 24⟩-⟨19, 27⟩', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 24, 'synthetic': False}, 'end': {'line': 19, 'character': 27, 'synthetic': False}}}], 'type': 'Completion-Id', 'range': {'start': {'line': 19, 'character': 24, 'synthetic': False}, 'end': {'line': 19, 'character': 27, 'synthetic': False}}}, {'text': '[Term] n (isBinder := true) : Nat @ ⟨19, 20⟩-⟨19, 21⟩', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 20, 'synthetic': False}, 'end': {'line': 19, 'character': 21, 'synthetic': False}}}, {'text': '[Term] n + 0 = n : Prop @ ⟨19, 31⟩-⟨19, 40⟩ @ «_aux_Init_Notation___macroRules_term_=__2»', 'children': [{'text': '[MacroExpansion]', 'children': [{'text': '[Term] n + 0 = n : Prop @ ⟨19, 31⟩†-⟨19, 40⟩† @ Lean.Elab.Term.Op.elabBinRel', 'children': [{'text': '[Term] n + 0 = n : Prop @ ⟨19, 31⟩†-⟨19, 40⟩†', 'children': [{'text': '[Term] n + 0 : Nat @ ⟨19, 31⟩-⟨19, 36⟩ @ «_aux_Init_Notation___macroRules_term_+__2»', 'children': [{'text': '[MacroExpansion]', 'children': [{'text': '[Term] n + 0 : Nat @ ⟨19, 31⟩†-⟨19, 36⟩†', 'children': [{'text': '[Completion-Id] Eq✝ : none @ ⟨19, 31⟩†-⟨19, 40⟩†', 'children': [{'text': '[Completion-Id] HAdd.hAdd✝ : none @ ⟨19, 31⟩†-⟨19, 36⟩†', 'children': [{'text': '[Term] n : Nat @ ⟨19, 31⟩-⟨19, 32⟩ @ Lean.Elab.Term.elabIdent', 'children': [{'text': '[Completion-Id] n : none @ ⟨19, 31⟩-⟨19, 32⟩', 'children': [{'text': '[Term] n : Nat @ ⟨19, 31⟩-⟨19, 32⟩', 'children': [{'text': '[Term] 0 : Nat @ ⟨19, 35⟩-⟨19, 36⟩ @ Lean.Elab.Term.elabNumLit', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 35, 'synthetic': False}, 'end': {'line': 19, 'character': 36, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Term.elabNumLit'}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': False}, 'end': {'line': 19, 'character': 32, 'synthetic': False}}}], 'type': 'Completion-Id', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': False}, 'end': {'line': 19, 'character': 32, 'synthetic': False}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': False}, 'end': {'line': 19, 'character': 32, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Term.elabIdent'}], 'type': 'Completion-Id', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': True}, 'end': {'line': 19, 'character': 36, 'synthetic': True}}}, {'text': '[Term] n : Nat @ ⟨19, 39⟩-⟨19, 40⟩ @ Lean.Elab.Term.elabIdent', 'children': [{'text': '[Completion-Id] n : none @ ⟨19, 39⟩-⟨19, 40⟩', 'children': [{'text': '[Term] n : Nat @ ⟨19, 39⟩-⟨19, 40⟩', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 39, 'synthetic': False}, 'end': {'line': 19, 'character': 40, 'synthetic': False}}}], 'type': 'Completion-Id', 'range': {'start': {'line': 19, 'character': 39, 'synthetic': False}, 'end': {'line': 19, 'character': 40, 'synthetic': False}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 39, 'synthetic': False}, 'end': {'line': 19, 'character': 40, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Term.elabIdent'}], 'type': 'Completion-Id', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': True}, 'end': {'line': 19, 'character': 40, 'synthetic': True}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': True}, 'end': {'line': 19, 'character': 36, 'synthetic': True}}}], 'type': 'MacroExpansion', 'extra': 'n + 0\n===>\nbinop% HAdd.hAdd✝ n 0'}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': False}, 'end': {'line': 19, 'character': 36, 'synthetic': False}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': True}, 'end': {'line': 19, 'character': 40, 'synthetic': True}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': True}, 'end': {'line': 19, 'character': 40, 'synthetic': True}}, 'elaborator': 'Lean.Elab.Term.Op.elabBinRel'}], 'type': 'MacroExpansion', 'extra': 'n + 0 = n\n===>\nbinrel% Eq✝ (n + 0) n'}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 31, 'synthetic': False}, 'end': {'line': 19, 'character': 40, 'synthetic': False}}}, {'text': '[CustomInfo(Lean.Elab.Term.AsyncBodyInfo)]', 'children': [{'text': '[Term] incomplete (isBinder := true) : ∀ (n : Nat), n + 0 = n @ ⟨19, 8⟩-⟨19, 18⟩', 'children': [{'text': '[Term] n (isBinder := true) : Nat @ ⟨19, 20⟩-⟨19, 21⟩', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 20, 'synthetic': False}, 'end': {'line': 19, 'character': 21, 'synthetic': False}}}, {'text': '[CustomInfo(Lean.Elab.Term.BodyInfo)]', 'children': [{'text': '[Tactic] @ ⟨19, 44⟩-⟨19, 52⟩', 'children': [{'text': '[Tactic] @ ⟨19, 44⟩-⟨19, 46⟩', 'children': [{'text': '[Tactic] @ ⟨19, 47⟩-⟨19, 52⟩ @ Lean.Elab.Tactic.evalTacticSeq', 'children': [{'text': '[Tactic] @ ⟨19, 47⟩-⟨19, 52⟩ @ Lean.Elab.Tactic.evalTacticSeq1Indented', 'children': [{'text': '[Tactic] @ ⟨19, 47⟩-⟨19, 52⟩ @ Lean.Parser.Tactic._aux_Init_Tactics___macroRules_Lean_Parser_Tactic_tacticSorry_1', 'children': [{'text': '[Tactic] @ ⟨19, 47⟩†-⟨19, 52⟩† @ Lean.Elab.Tactic.evalExact', 'children': [{'text': '[Term] sorry : n + 0 = n @ ⟨19, 47⟩†-⟨19, 52⟩† @ Lean.Elab.Term.elabSorry', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 47, 'synthetic': True}, 'end': {'line': 19, 'character': 52, 'synthetic': True}}, 'elaborator': 'Lean.Elab.Term.elabSorry'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 47, 'synthetic': True}, 'end': {'line': 19, 'character': 52, 'synthetic': True}}, 'elaborator': 'Lean.Elab.Tactic.evalExact', 'extra': '(Tactic.exact "exact" (Term.sorry "sorry"))\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 47, 'synthetic': False}, 'end': {'line': 19, 'character': 52, 'synthetic': False}}, 'elaborator': 'Lean.Parser.Tactic._aux_Init_Tactics___macroRules_Lean_Parser_Tactic_tacticSorry_1', 'extra': '(Tactic.tacticSorry "sorry")\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 47, 'synthetic': False}, 'end': {'line': 19, 'character': 52, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Tactic.evalTacticSeq1Indented', 'extra': '(Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")])\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 47, 'synthetic': False}, 'end': {'line': 19, 'character': 52, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Tactic.evalTacticSeq', 'extra': '(Tactic.tacticSeq (Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")]))\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 44, 'synthetic': False}, 'end': {'line': 19, 'character': 46, 'synthetic': False}}, 'extra': '"by"\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'Tactic', 'range': {'start': {'line': 19, 'character': 44, 'synthetic': False}, 'end': {'line': 19, 'character': 52, 'synthetic': False}}, 'extra': '(Term.byTactic "by" (Tactic.tacticSeq (Tactic.tacticSeq1Indented [(Tactic.tacticSorry "sorry")])))\nbefore\nn : Nat\n⊢ n + 0 = n\nafter no goals'}], 'type': 'CustomInfo(Lean.Elab.Term.BodyInfo)'}, {'text': '[Term] incomplete (isBinder := true) : ∀ (n : Nat), n + 0 = n @ ⟨19, 8⟩-⟨19, 18⟩', 'children': [], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 8, 'synthetic': False}, 'end': {'line': 19, 'character': 18, 'synthetic': False}}}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 8, 'synthetic': False}, 'end': {'line': 19, 'character': 18, 'synthetic': False}}}], 'type': 'CustomInfo(Lean.Elab.Term.AsyncBodyInfo)'}], 'type': 'Term', 'range': {'start': {'line': 19, 'character': 24, 'synthetic': False}, 'end': {'line': 19, 'character': 27, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Term.elabIdent'}], 'type': 'Command', 'range': {'start': {'line': 19, 'character': 0, 'synthetic': False}, 'end': {'line': 19, 'character': 52, 'synthetic': False}}, 'elaborator': 'Lean.Elab.Command.elabDeclaration'}

    Args:
        info_tree_str (str): The string representation of a Lean info tree.

    Returns:
        dict: A nested dictionary representing the parsed info tree.
    """
    lines = info_tree_str.strip().splitlines()
    stack = [{"children": []}]

    for line in lines:
        if match := node_pattern.match(line):
            level = len(match.group(1))
            text = match.group(2)
            node = {"text": text, "children": []}

            # Extract type, range information and elaborator
            type_match = type_pattern.match(text)
            if type_match:
                node["type"] = type_match.group("type")

            range_match = range_pattern.search(text)
            if range_match:
                node["range"] = {
                    "start": {
                        "line": int(range_match.group("start_line")),
                        "character": int(range_match.group("start_char")),
                        "synthetic": bool(range_match.group("start_syn")),
                    },
                    "end": {
                        "line": int(range_match.group("end_line")),
                        "character": int(range_match.group("end_char")),
                        "synthetic": bool(range_match.group("end_syn")),
                    },
                }

            elaborator_match = elaborator_pattern.findall(text)
            if elaborator_match:
                node["elaborator"] = elaborator_match[-1]  # Only use last elaborator

            while len(stack) > level + 1:
                stack.pop()
            stack[-1]["children"].append(node)
            stack.append(node)
        else:
            current = stack[-1]
            current.setdefault("extra", []).append(line.strip())

    root = stack[0]["children"][0]
    root = _parse_goals(root)
    root = _flatten_extra(root)
    return root


def _parse_goals(node: dict) -> dict:
    """Helper function: Parse out goals for Tactic nodes."""
    node["children"] = [_parse_goals(child) for child in node.get("children", [])]

    if node.get("type") == "TacticInfo" or node["text"].startswith("Tactic"):
        extra = node.get("extra", [])
        if extra:
            before_idx = None
            after_idx = None
            for i, line in enumerate(extra):
                if line.startswith("before"):
                    before_idx = i
                elif line.startswith("after"):
                    after_idx = i
            if before_idx is not None and after_idx is not None:
                before = extra[before_idx:after_idx]
                before[0] = before[0].replace("before", "")
                node["goals_before"] = "\n".join(
                    extra[before_idx + 1 : after_idx]
                ).strip()
                after = extra[after_idx:]
                after[0] = after[0].replace("after", "")
                node["goals_after"] = "\n".join(after).strip()
    return node


def _flatten_extra(node: dict) -> dict:
    """Helper function: Flatten the extra field into a single string."""
    if "extra" in node:
        node["extra"] = "\n".join(node["extra"]).strip()
    for child in node.get("children", []):
        _flatten_extra(child)
    return node
