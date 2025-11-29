"""
Agent Orchestrator — Tool Definitions
======================================
Version 1.0 — November 2025

Tools are organized using progressive disclosure to minimize context usage.
Instead of loading all tool definitions upfront, workers navigate a filesystem
structure and load only the tools they need.

Architecture based on: https://www.anthropic.com/engineering/code-execution-with-mcp

Directory Structure:
--------------------
tools/
├── TOOLS_INDEX.md          # High-level catalog (names + one-line descriptions)
├── filesystem/
│   ├── TOOL.md             # Detailed docs for this category
│   ├── read_file.py
│   ├── write_file.py
│   └── list_directory.py
├── git/
│   ├── TOOL.md
│   ├── commit.py
│   ├── diff.py
│   └── merge.py
├── web/
│   ├── TOOL.md
│   ├── search.py
│   └── fetch.py
├── code_execution/
│   ├── TOOL.md
│   ├── run_python.py
│   └── run_shell.py
└── search_tools.py         # Meta-tool for finding tools

Workers use progressive disclosure:
1. Read TOOLS_INDEX.md to see available categories
2. Read category/TOOL.md for detailed docs on relevant tools
3. Import only the specific tools needed
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from pathlib import Path


# =============================================================================
# TOOL METADATA
# =============================================================================

class ToolCategory(str, Enum):
    """Categories of tools available to workers."""
    FILESYSTEM = "filesystem"
    GIT = "git"
    WEB = "web"
    CODE_EXECUTION = "code_execution"
    DATABASE = "database"
    COMMUNICATION = "communication"  # Future: Slack, email, etc.


class DetailLevel(str, Enum):
    """How much detail to return when searching for tools."""
    NAME_ONLY = "name_only"           # Just tool names
    NAME_DESCRIPTION = "name_desc"    # Names + one-line descriptions
    FULL_SCHEMA = "full_schema"       # Complete parameter schemas


@dataclass
class ToolParameter:
    """A single parameter for a tool."""
    name: str
    type: str                         # "string", "int", "bool", "list", "dict", etc.
    description: str
    required: bool = True
    default: Any = None
    enum_values: Optional[List[str]] = None  # For constrained choices


@dataclass
class ToolDefinition:
    """
    Complete definition of a tool.
    
    Designed for progressive disclosure — can be serialized at different
    detail levels depending on what the worker needs.
    """
    name: str                         # e.g., "read_file"
    category: ToolCategory
    description: str                  # One-line description
    detailed_docs: str                # Full documentation (for TOOL.md)
    parameters: List[ToolParameter]
    returns: str                      # Description of return value
    examples: List[str] = field(default_factory=list)  # Usage examples
    
    # Metadata
    requires_confirmation: bool = False  # Human approval needed?
    is_destructive: bool = False         # Can it delete/modify data?
    estimated_latency: str = "fast"      # "fast", "medium", "slow"
    
    def to_name_only(self) -> str:
        """Return just the name."""
        return self.name
    
    def to_name_description(self) -> str:
        """Return name and one-line description."""
        return f"{self.name}: {self.description}"
    
    def to_full_schema(self) -> Dict[str, Any]:
        """Return complete schema for tool calling."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {
                    p.name: {
                        "type": p.type,
                        "description": p.description,
                        **({"enum": p.enum_values} if p.enum_values else {}),
                        **({"default": p.default} if p.default is not None else {}),
                    }
                    for p in self.parameters
                },
                "required": [p.name for p in self.parameters if p.required],
            },
            "returns": self.returns,
        }
    
    def to_detail_level(self, level: DetailLevel) -> Union[str, Dict[str, Any]]:
        """Return tool info at specified detail level."""
        if level == DetailLevel.NAME_ONLY:
            return self.to_name_only()
        elif level == DetailLevel.NAME_DESCRIPTION:
            return self.to_name_description()
        else:
            return self.to_full_schema()


# =============================================================================
# TOOLS INDEX (TOOLS_INDEX.md equivalent)
# =============================================================================

TOOLS_INDEX = """# Available Tools

Workers can access the following tool categories. Read the category's TOOL.md 
for detailed documentation before using.

## Categories

### filesystem
File and directory operations within the task's git worktree.
- read_file: Read contents of a file
- write_file: Write content to a file (creates or overwrites)
- append_file: Append content to existing file
- list_directory: List files and directories
- file_exists: Check if a file exists
- delete_file: Delete a file (requires confirmation)

### git
Git operations for version control.
- commit: Commit staged changes with message
- diff: Show changes between commits or working tree
- status: Show working tree status
- add: Stage files for commit
- log: Show commit history
- merge: Merge branches (Strategist only)

### web
Web search and fetching.
- search: Search the web for information
- fetch: Fetch content from a URL
- fetch_structured: Fetch and parse structured data (JSON, XML)

### code_execution
Run code in sandboxed environment.
- run_python: Execute Python code
- run_shell: Execute shell commands (restricted)
- run_tests: Run test suite

### database (future)
Database operations.
- query: Execute read-only SQL query
- execute: Execute SQL statement (requires confirmation)

---

To use a tool:
1. Read the relevant TOOL.md for detailed documentation
2. Import only the tools you need
3. Call with required parameters

Use `search_tools(query, detail_level)` to find specific tools.
"""


# =============================================================================
# FILESYSTEM TOOLS
# =============================================================================

FILESYSTEM_TOOL_MD = """# Filesystem Tools

Operations for reading and writing files within your task's git worktree.

## Important Notes

- All paths are relative to your worktree root
- You cannot access files outside your worktree
- Changes are tracked by git automatically
- Use `git commit` to save your work

## Tools

### read_file

Read the contents of a file.

**Parameters:**
- `path` (string, required): Relative path to the file
- `encoding` (string, optional): File encoding. Default: "utf-8"

**Returns:** File contents as string

**Example:**
```python
content = read_file(path="src/main.py")
```

### write_file

Write content to a file. Creates the file if it doesn't exist, overwrites if it does.

**Parameters:**
- `path` (string, required): Relative path to the file
- `content` (string, required): Content to write
- `encoding` (string, optional): File encoding. Default: "utf-8"

**Returns:** Success confirmation with bytes written

**Example:**
```python
write_file(path="src/utils.py", content="def helper():\\n    pass")
```

### append_file

Append content to an existing file.

**Parameters:**
- `path` (string, required): Relative path to the file
- `content` (string, required): Content to append

**Returns:** Success confirmation

### list_directory

List files and directories at a path.

**Parameters:**
- `path` (string, optional): Directory path. Default: "." (current)
- `recursive` (bool, optional): Include subdirectories. Default: false
- `pattern` (string, optional): Glob pattern filter. Default: "*"

**Returns:** List of file/directory names with metadata

**Example:**
```python
files = list_directory(path="src", recursive=True, pattern="*.py")
```

### file_exists

Check if a file or directory exists.

**Parameters:**
- `path` (string, required): Path to check

**Returns:** Boolean

### delete_file

Delete a file. **Requires confirmation.**

**Parameters:**
- `path` (string, required): Path to delete
- `confirm` (bool, required): Must be True to proceed

**Returns:** Success confirmation
"""

FILESYSTEM_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="read_file",
        category=ToolCategory.FILESYSTEM,
        description="Read contents of a file",
        detailed_docs="Read the contents of a file from the worktree.",
        parameters=[
            ToolParameter(name="path", type="string", description="Relative path to the file"),
            ToolParameter(name="encoding", type="string", description="File encoding", required=False, default="utf-8"),
        ],
        returns="File contents as string",
        examples=['read_file(path="src/main.py")'],
    ),
    ToolDefinition(
        name="write_file",
        category=ToolCategory.FILESYSTEM,
        description="Write content to a file (creates or overwrites)",
        detailed_docs="Write content to a file. Creates if doesn't exist, overwrites if it does.",
        parameters=[
            ToolParameter(name="path", type="string", description="Relative path to the file"),
            ToolParameter(name="content", type="string", description="Content to write"),
            ToolParameter(name="encoding", type="string", description="File encoding", required=False, default="utf-8"),
        ],
        returns="Success confirmation with bytes written",
        examples=['write_file(path="src/utils.py", content="def helper():\\n    pass")'],
        is_destructive=True,
    ),
    ToolDefinition(
        name="append_file",
        category=ToolCategory.FILESYSTEM,
        description="Append content to existing file",
        detailed_docs="Append content to the end of an existing file.",
        parameters=[
            ToolParameter(name="path", type="string", description="Relative path to the file"),
            ToolParameter(name="content", type="string", description="Content to append"),
        ],
        returns="Success confirmation",
        is_destructive=True,
    ),
    ToolDefinition(
        name="list_directory",
        category=ToolCategory.FILESYSTEM,
        description="List files and directories",
        detailed_docs="List files and directories at a given path.",
        parameters=[
            ToolParameter(name="path", type="string", description="Directory path", required=False, default="."),
            ToolParameter(name="recursive", type="bool", description="Include subdirectories", required=False, default=False),
            ToolParameter(name="pattern", type="string", description="Glob pattern filter", required=False, default="*"),
        ],
        returns="List of file/directory names with metadata",
        examples=['list_directory(path="src", recursive=True, pattern="*.py")'],
    ),
    ToolDefinition(
        name="file_exists",
        category=ToolCategory.FILESYSTEM,
        description="Check if a file exists",
        detailed_docs="Check if a file or directory exists at the given path.",
        parameters=[
            ToolParameter(name="path", type="string", description="Path to check"),
        ],
        returns="Boolean indicating existence",
    ),
    ToolDefinition(
        name="delete_file",
        category=ToolCategory.FILESYSTEM,
        description="Delete a file (requires confirmation)",
        detailed_docs="Delete a file from the worktree. Requires explicit confirmation.",
        parameters=[
            ToolParameter(name="path", type="string", description="Path to delete"),
            ToolParameter(name="confirm", type="bool", description="Must be True to proceed"),
        ],
        returns="Success confirmation",
        requires_confirmation=True,
        is_destructive=True,
    ),
]


# =============================================================================
# GIT TOOLS
# =============================================================================

GIT_TOOL_MD = """# Git Tools

Version control operations for your task branch.

## Important Notes

- You're working in a dedicated worktree for your task
- Commit frequently to save your progress
- Your commits will be reviewed before merging to main
- Only Strategist can perform merges

## Tools

### commit

Commit staged changes with a message.

**Parameters:**
- `message` (string, required): Commit message
- `add_all` (bool, optional): Stage all changes first. Default: false

**Returns:** Commit hash

**Example:**
```python
commit(message="Add user authentication module", add_all=True)
```

### diff

Show changes between commits or working tree.

**Parameters:**
- `target` (string, optional): Commit/branch to diff against. Default: "HEAD"
- `path` (string, optional): Limit diff to specific path

**Returns:** Diff output as string

### status

Show working tree status.

**Parameters:** None

**Returns:** Status output showing staged, unstaged, and untracked files

### add

Stage files for commit.

**Parameters:**
- `paths` (list[string], required): Files to stage
- `all` (bool, optional): Stage all changes. Default: false

**Returns:** List of staged files

### log

Show commit history.

**Parameters:**
- `count` (int, optional): Number of commits to show. Default: 10
- `oneline` (bool, optional): Compact format. Default: true

**Returns:** Commit history

### merge (Strategist only)

Merge a branch into current branch.

**Parameters:**
- `branch` (string, required): Branch to merge
- `message` (string, optional): Merge commit message

**Returns:** Merge result with any conflicts
"""

GIT_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="git_commit",
        category=ToolCategory.GIT,
        description="Commit staged changes with message",
        detailed_docs="Commit currently staged changes with a descriptive message.",
        parameters=[
            ToolParameter(name="message", type="string", description="Commit message"),
            ToolParameter(name="add_all", type="bool", description="Stage all changes first", required=False, default=False),
        ],
        returns="Commit hash",
        examples=['git_commit(message="Add user authentication module", add_all=True)'],
    ),
    ToolDefinition(
        name="git_diff",
        category=ToolCategory.GIT,
        description="Show changes between commits or working tree",
        detailed_docs="Show differences between commits, branches, or working tree.",
        parameters=[
            ToolParameter(name="target", type="string", description="Commit/branch to diff against", required=False, default="HEAD"),
            ToolParameter(name="path", type="string", description="Limit diff to specific path", required=False),
        ],
        returns="Diff output as string",
    ),
    ToolDefinition(
        name="git_status",
        category=ToolCategory.GIT,
        description="Show working tree status",
        detailed_docs="Show the current status of the working tree.",
        parameters=[],
        returns="Status output showing staged, unstaged, and untracked files",
    ),
    ToolDefinition(
        name="git_add",
        category=ToolCategory.GIT,
        description="Stage files for commit",
        detailed_docs="Stage specified files for the next commit.",
        parameters=[
            ToolParameter(name="paths", type="list", description="Files to stage"),
            ToolParameter(name="all", type="bool", description="Stage all changes", required=False, default=False),
        ],
        returns="List of staged files",
    ),
    ToolDefinition(
        name="git_log",
        category=ToolCategory.GIT,
        description="Show commit history",
        detailed_docs="Show the commit history for the current branch.",
        parameters=[
            ToolParameter(name="count", type="int", description="Number of commits to show", required=False, default=10),
            ToolParameter(name="oneline", type="bool", description="Compact format", required=False, default=True),
        ],
        returns="Commit history",
    ),
    ToolDefinition(
        name="git_merge",
        category=ToolCategory.GIT,
        description="Merge a branch (Strategist only)",
        detailed_docs="Merge a branch into the current branch. Only available to Strategist.",
        parameters=[
            ToolParameter(name="branch", type="string", description="Branch to merge"),
            ToolParameter(name="message", type="string", description="Merge commit message", required=False),
        ],
        returns="Merge result with any conflicts",
        requires_confirmation=True,
        is_destructive=True,
    ),
]


# =============================================================================
# WEB TOOLS
# =============================================================================

WEB_TOOL_MD = """# Web Tools

Search the web and fetch content from URLs.

## Important Notes

- Use search for general research and finding sources
- Use fetch to get full content from specific URLs
- Be mindful of rate limits
- Respect robots.txt and terms of service

## Tools

### search

Search the web for information.

**Parameters:**
- `query` (string, required): Search query
- `num_results` (int, optional): Number of results. Default: 10

**Returns:** List of search results with title, URL, and snippet

**Example:**
```python
results = search(query="Python async best practices", num_results=5)
```

### fetch

Fetch content from a URL.

**Parameters:**
- `url` (string, required): URL to fetch
- `timeout` (int, optional): Timeout in seconds. Default: 30

**Returns:** Page content (text or structured data)

**Example:**
```python
content = fetch(url="https://docs.python.org/3/library/asyncio.html")
```

### fetch_structured

Fetch and parse structured data (JSON, XML).

**Parameters:**
- `url` (string, required): URL to fetch
- `format` (string, optional): Expected format ("json", "xml"). Default: auto-detect

**Returns:** Parsed data structure
"""

WEB_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="web_search",
        category=ToolCategory.WEB,
        description="Search the web for information",
        detailed_docs="Perform a web search and return relevant results.",
        parameters=[
            ToolParameter(name="query", type="string", description="Search query"),
            ToolParameter(name="num_results", type="int", description="Number of results", required=False, default=10),
        ],
        returns="List of search results with title, URL, and snippet",
        examples=['web_search(query="Python async best practices", num_results=5)'],
        estimated_latency="medium",
    ),
    ToolDefinition(
        name="web_fetch",
        category=ToolCategory.WEB,
        description="Fetch content from a URL",
        detailed_docs="Fetch the content of a web page.",
        parameters=[
            ToolParameter(name="url", type="string", description="URL to fetch"),
            ToolParameter(name="timeout", type="int", description="Timeout in seconds", required=False, default=30),
        ],
        returns="Page content (text or structured data)",
        examples=['web_fetch(url="https://docs.python.org/3/library/asyncio.html")'],
        estimated_latency="medium",
    ),
    ToolDefinition(
        name="web_fetch_structured",
        category=ToolCategory.WEB,
        description="Fetch and parse structured data (JSON, XML)",
        detailed_docs="Fetch and automatically parse structured data from a URL.",
        parameters=[
            ToolParameter(name="url", type="string", description="URL to fetch"),
            ToolParameter(name="format", type="string", description="Expected format", required=False, 
                         enum_values=["json", "xml", "auto"]),
        ],
        returns="Parsed data structure",
        estimated_latency="medium",
    ),
]


# =============================================================================
# CODE EXECUTION TOOLS
# =============================================================================

CODE_EXECUTION_TOOL_MD = """# Code Execution Tools

Run code in a sandboxed environment.

## Important Notes

- Code runs in an isolated sandbox
- Limited to approved libraries
- Execution has time and memory limits
- Output is captured and returned

## Tools

### run_python

Execute Python code in sandbox.

**Parameters:**
- `code` (string, required): Python code to execute
- `timeout` (int, optional): Max execution time in seconds. Default: 30

**Returns:** Execution result with stdout, stderr, and return value

**Example:**
```python
result = run_python(code=\"\"\"
import json
data = {"key": "value"}
print(json.dumps(data, indent=2))
\"\"\")
```

### run_shell

Execute shell commands (restricted).

**Parameters:**
- `command` (string, required): Shell command to run
- `timeout` (int, optional): Max execution time in seconds. Default: 30

**Returns:** Command output (stdout and stderr)

**Allowed commands:** ls, cat, head, tail, grep, find, wc, sort, uniq, diff, echo

### run_tests

Run the test suite for a specific path.

**Parameters:**
- `path` (string, optional): Test file or directory. Default: "tests/"
- `pattern` (string, optional): Test pattern. Default: "test_*.py"
- `verbose` (bool, optional): Verbose output. Default: false

**Returns:** Test results with pass/fail counts and details
"""

CODE_EXECUTION_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="run_python",
        category=ToolCategory.CODE_EXECUTION,
        description="Execute Python code in sandbox",
        detailed_docs="Execute Python code in an isolated sandbox environment.",
        parameters=[
            ToolParameter(name="code", type="string", description="Python code to execute"),
            ToolParameter(name="timeout", type="int", description="Max execution time in seconds", required=False, default=30),
        ],
        returns="Execution result with stdout, stderr, and return value",
        examples=['run_python(code="print(1 + 1)")'],
        estimated_latency="medium",
    ),
    ToolDefinition(
        name="run_shell",
        category=ToolCategory.CODE_EXECUTION,
        description="Execute shell commands (restricted)",
        detailed_docs="Execute restricted shell commands. Only safe commands are allowed.",
        parameters=[
            ToolParameter(name="command", type="string", description="Shell command to run"),
            ToolParameter(name="timeout", type="int", description="Max execution time in seconds", required=False, default=30),
        ],
        returns="Command output (stdout and stderr)",
        estimated_latency="fast",
    ),
    ToolDefinition(
        name="run_tests",
        category=ToolCategory.CODE_EXECUTION,
        description="Run test suite",
        detailed_docs="Run pytest on the specified path or directory.",
        parameters=[
            ToolParameter(name="path", type="string", description="Test file or directory", required=False, default="tests/"),
            ToolParameter(name="pattern", type="string", description="Test pattern", required=False, default="test_*.py"),
            ToolParameter(name="verbose", type="bool", description="Verbose output", required=False, default=False),
        ],
        returns="Test results with pass/fail counts and details",
        estimated_latency="slow",
    ),
]


# =============================================================================
# TOOL REGISTRY
# =============================================================================

@dataclass
class ToolRegistry:
    """
    Registry of all available tools.
    
    Supports progressive disclosure via search_tools.
    """
    tools: Dict[str, ToolDefinition] = field(default_factory=dict)
    categories: Dict[ToolCategory, List[str]] = field(default_factory=dict)
    
    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self.tools[tool.name] = tool
        if tool.category not in self.categories:
            self.categories[tool.category] = []
        self.categories[tool.category].append(tool.name)
    
    def register_all(self, tools: List[ToolDefinition]) -> None:
        """Register multiple tools."""
        for tool in tools:
            self.register(tool)
    
    def get_index(self) -> str:
        """Get the TOOLS_INDEX.md content."""
        return TOOLS_INDEX
    
    def get_category_docs(self, category: ToolCategory) -> str:
        """Get the TOOL.md for a category."""
        docs = {
            ToolCategory.FILESYSTEM: FILESYSTEM_TOOL_MD,
            ToolCategory.GIT: GIT_TOOL_MD,
            ToolCategory.WEB: WEB_TOOL_MD,
            ToolCategory.CODE_EXECUTION: CODE_EXECUTION_TOOL_MD,
        }
        return docs.get(category, f"# {category.value}\n\nNo documentation available.")
    
    def search_tools(
        self, 
        query: str, 
        detail_level: DetailLevel = DetailLevel.NAME_DESCRIPTION,
        category: Optional[ToolCategory] = None
    ) -> List[Union[str, Dict[str, Any]]]:
        """
        Search for tools matching a query.
        
        This is the meta-tool that workers use to find relevant tools
        without loading all definitions upfront.
        
        Args:
            query: Search terms (matched against name and description)
            detail_level: How much detail to return
            category: Optional category filter
            
        Returns:
            List of tool info at the specified detail level
        """
        query_lower = query.lower()
        results = []
        
        for name, tool in self.tools.items():
            # Filter by category if specified
            if category and tool.category != category:
                continue
            
            # Match against name and description
            if (query_lower in name.lower() or 
                query_lower in tool.description.lower() or
                query_lower in tool.detailed_docs.lower()):
                results.append(tool.to_detail_level(detail_level))
        
        return results
    
    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        """Get a specific tool by name."""
        return self.tools.get(name)
    
    def get_tools_for_worker(self, worker_profile: str) -> List[str]:
        """
        Get default tool categories for a worker profile.
        
        Workers can access additional tools via search_tools,
        but these are the recommended starting points.
        """
        defaults = {
            "planner_worker": [ToolCategory.FILESYSTEM, ToolCategory.WEB],
            "code_worker": [ToolCategory.FILESYSTEM, ToolCategory.GIT, ToolCategory.CODE_EXECUTION],
            "test_worker": [ToolCategory.FILESYSTEM, ToolCategory.GIT, ToolCategory.CODE_EXECUTION],
            "research_worker": [ToolCategory.WEB, ToolCategory.FILESYSTEM],
            "writer_worker": [ToolCategory.FILESYSTEM, ToolCategory.WEB],
        }
        
        categories = defaults.get(worker_profile, [ToolCategory.FILESYSTEM])
        tool_names = []
        for cat in categories:
            tool_names.extend(self.categories.get(cat, []))
        return tool_names


# =============================================================================
# SEARCH TOOLS META-TOOL
# =============================================================================

SEARCH_TOOLS_DEFINITION = ToolDefinition(
    name="search_tools",
    category=ToolCategory.FILESYSTEM,  # Meta-category
    description="Find available tools matching a query",
    detailed_docs="""
Search for tools by keyword. Use this to discover tools without loading all 
definitions upfront.

**Detail levels:**
- `name_only`: Just tool names (minimal tokens)
- `name_desc`: Names + one-line descriptions (recommended for discovery)
- `full_schema`: Complete parameter schemas (use when ready to call)

**Example workflow:**
1. search_tools(query="file", detail_level="name_desc") → find file-related tools
2. search_tools(query="write_file", detail_level="full_schema") → get full schema
3. Call the tool with correct parameters
""",
    parameters=[
        ToolParameter(name="query", type="string", description="Search terms"),
        ToolParameter(name="detail_level", type="string", description="Amount of detail", 
                     required=False, default="name_desc",
                     enum_values=["name_only", "name_desc", "full_schema"]),
        ToolParameter(name="category", type="string", description="Filter by category",
                     required=False, enum_values=["filesystem", "git", "web", "code_execution"]),
    ],
    returns="List of matching tools at specified detail level",
    examples=[
        'search_tools(query="file", detail_level="name_desc")',
        'search_tools(query="commit", category="git", detail_level="full_schema")',
    ],
)


# =============================================================================
# INITIALIZE DEFAULT REGISTRY
# =============================================================================

def create_default_registry() -> ToolRegistry:
    """Create and populate the default tool registry."""
    registry = ToolRegistry()
    
    # Register all tool categories
    registry.register_all(FILESYSTEM_TOOLS)
    registry.register_all(GIT_TOOLS)
    registry.register_all(WEB_TOOLS)
    registry.register_all(CODE_EXECUTION_TOOLS)
    
    # Register the meta-tool
    registry.register(SEARCH_TOOLS_DEFINITION)
    
    return registry


# Default instance
DEFAULT_REGISTRY = create_default_registry()


# =============================================================================
# TOOL IMPLEMENTATION STUBS
# =============================================================================

"""
Actual tool implementations would go here or in separate files.
These are stubs showing the expected signatures.
"""

async def read_file(path: str, encoding: str = "utf-8") -> str:
    """Read file contents."""
    # Implementation: Use worktree manager to read file
    pass

async def write_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """Write file contents."""
    # Implementation: Use worktree manager to write file
    pass

async def git_commit(message: str, add_all: bool = False) -> str:
    """Commit changes."""
    # Implementation: Use git_filesystem_spec functions
    pass

async def web_search(query: str, num_results: int = 10) -> List[Dict[str, Any]]:
    """Search the web."""
    # Implementation: Use search API (Brave, Google, etc.)
    pass

async def run_python(code: str, timeout: int = 30) -> Dict[str, Any]:
    """Execute Python code."""
    # Implementation: Use sandboxed execution environment
    pass


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    # Enums
    "ToolCategory",
    "DetailLevel",
    # Dataclasses
    "ToolParameter",
    "ToolDefinition",
    "ToolRegistry",
    # Documentation
    "TOOLS_INDEX",
    "FILESYSTEM_TOOL_MD",
    "GIT_TOOL_MD",
    "WEB_TOOL_MD",
    "CODE_EXECUTION_TOOL_MD",
    # Tool definitions
    "FILESYSTEM_TOOLS",
    "GIT_TOOLS",
    "WEB_TOOLS",
    "CODE_EXECUTION_TOOLS",
    "SEARCH_TOOLS_DEFINITION",
    # Registry
    "DEFAULT_REGISTRY",
    "create_default_registry",
]
