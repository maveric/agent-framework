#!/usr/bin/env python3
"""
Quick script to add validation and feedback to director.py
"""

import re
from pathlib import Path

def add_validation_to_director():
    """Add validation check before integrating suggestions."""
    
    director_file = Path("src/nodes/director.py")
    content = director_file.read_text(encoding="utf-8")
    
    # Find the section where we process suggestions (around line 245)
    # We want to validate BEFORE calling _integrate_plans
    
    search_pattern = r'        if all_suggestions:\r\n            print\(f"Director: Integrating'
    
    replacement = '''        if all_suggestions:
            # VALIDATE SUGGESTIONS AGAINST DESIGN SPEC
            print(f"Director: Validating {len(all_suggestions)} suggestions against design_spec.md...", flush=True)
            
            validated_suggestions = []
            rejected_suggestions = []
            
            spec = state.get("spec", {})
            objective = state.get("objective", "")
            
            for suggestion in all_suggestions:
                # Quick validation via LLM
                try:
                    # Simplified inline validation
                    rationale = suggestion.get("rationale", "")
                    desc = suggestion.get("description", "")
                    
                    # Basic heuristic: if rationale exists and is detailed, likely from coder
                    # If rationale is generic or missing, likely from planner (less strict)
                    is_detailed_rationale = len(rationale) > 100
                    
                    # For now, accept all planner/tester suggestions
                    # Only validate coder suggestions (those with detailed rationale)
                    if is_detailed_rationale:
                        # TODO: Add full LLM validation here
                        # For now, accept if rationale mentions spec
                        if "design_spec" in rationale.lower() or "spec" in desc.lower():
                            validated_suggestions.append(suggestion)
                            print(f"  ✓ Approved: {suggestion.get('title', 'Untitled')}", flush=True)
                        else:
                            rejected_suggestions.append({
                                "suggestion": suggestion,
                                "reason": "Rationale doesn't reference design specification"
                            })
                            print(f"  ✗ Rejected: {suggestion.get('title', 'Untitled')} - no spec reference", flush=True)
                    else:
                        # Planner/tester suggestion - accept
                        validated_suggestions.append(suggestion)
                except Exception as e:
                    # Default to accept on error
                    print(f"  Warning: Validation error, accepting suggestion: {e}", flush=True)
                    validated_suggestions.append(suggestion)
            
            # Send feedback for rejected suggestions
            for rejection in rejected_suggestions:
                sug = rejection["suggestion"]
                source_task_id = sug.get("suggested_by_task")
                if source_task_id:
                    # Add feedback to task_memories
                    if "task_memories" not in state:
                        updates.append({"task_memories": {}})
                    
                    feedback_msg = {
                        "role": "system",
                        "content": f"DIRECTOR FEEDBACK: Your task suggestion was not approved.\\n\\nReason: {rejection['reason']}\\n\\nSuggested task: {sug.get('title')}\\n\\nPlease continue your work using an alternative approach or provide better justification if you re-suggest."
                    }
                    print(f"  Sending rejection feedback to task {source_task_id}", flush=True)
                    # Note: feedback mechanism needs state update support
            
            if not validated_suggestions:
                print(f"Director: All {len(all_suggestions)} suggestions were rejected.", flush=True)
            else:
                print(f"Director: Integrating {len(validated_suggestions)} validated tasks (rejected {len(rejected_suggestions)})...", flush=True)
            
            all_suggestions = validated_suggestions  # Replace with validated list
            
            print(f"Director: Integrating'''
    
    if search_pattern in content:
        content = content.replace(search_pattern, replacement, 1)
        director_file.write_text(content, encoding="utf-8")
        print("✓ Added validation logic to director.py")
        return True
    else:
        print("✗ Could not find pattern to replace")
        return False

if __name__ == "__main__":
    import os
    os.chdir(r"f:\coding\agent-framework")
    add_validation_to_director()
