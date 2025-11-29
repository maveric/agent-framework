# Agent Rules & Guidelines

## Spec Immutability
**Do not modify files in the `spec` folder.**
These files represent the design source of truth. They serve as the reference for all implementation.

## Implementation Strategy
- **New Files Only:** All implementation must be done in new files. Do not modify the spec files to "implement" them.
- **Spec as Reference:** Use the spec files to guide your implementation logic, data structures, and architecture.

## Handling Deviations
If you must deviate from the spec (e.g., due to technical limitations, library changes, or better design discovery):
1. **Do not change the spec.**
2. **Document the deviation** in the comments of your implementation code.
3. **Explain why** the deviation was necessary (e.g., "Spec calls for X, but library Y requires Z").
